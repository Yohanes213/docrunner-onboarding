# DocRunner webhook handler

The same steps in both versions: verify the signature on the raw body,
check the account, apply each `delivery_id` once inside the same
transaction as the change, find the record by packet id, return quickly.

## Ruby (Rails)

```ruby
# config/routes.rb
post 'hooks/docrunner/:token' => 'docrunner_hooks#create'

# A table for delivery ids (unique per account), pruned after a week:
#   create_table :docrunner_deliveries do |t|
#     t.references :account, null: false
#     t.string :delivery_id, null: false
#     t.string :event
#     t.datetime :created_at, null: false
#     t.index %i[account_id delivery_id], unique: true
#   end

class DocrunnerHooksController < ActionController::API
  EVENTS = %w[Packet.Sent Packet.Completed Packet.Voided Submission.Opened Submitter.Opened Submitter.Signed Submitter.Declined].freeze

  def create
    account = Account.find_by(docrunner_webhook_token: params[:token]) or return head(:not_found)
    body = request.raw_post
    return head(:unauthorized) unless valid_signature?(body, request.headers['X-DocRunner-Signature'], account.docrunner_webhook_secret)

    payload = JSON.parse(body)
    result = receive(account, payload)
    Rails.logger.info("[docrunner] account #{account.id} #{payload['event'].to_s.first(60)}: #{result}")
    head :ok
  rescue JSON::ParserError
    head :bad_request
  end

  private

  def valid_signature?(body, header, secret)
    return false if secret.blank? || header.blank?

    expected = "sha256=#{OpenSSL::HMAC.hexdigest('SHA256', secret, body)}"
    ActiveSupport::SecurityUtils.secure_compare(expected, header.strip)
  end

  def receive(account, payload)
    event = payload['event'].to_s
    return :ignored unless EVENTS.include?(event)

    # Remember the account from the first verified delivery; ignore others after that.
    account.update!(docrunner_account_id: payload['account_id']) if account.docrunner_account_id.nil?
    return :other_account if payload['account_id'].to_s != account.docrunner_account_id.to_s

    Account.transaction do
      # Recorded with the change: if applying fails, the retry applies it again.
      # A savepoint, so a duplicate doesn't abort the outer transaction (Postgres).
      begin
        DocrunnerDelivery.transaction(requires_new: true) do
          account.docrunner_deliveries.create!(delivery_id: payload['delivery_id'], event: event, created_at: Time.current)
        end
      rescue ActiveRecord::RecordNotUnique
        return :duplicate
      end

      data = payload['data'].is_a?(Hash) ? payload['data'] : {}
      packet = data['packet'].is_a?(Hash) ? data['packet'] : {}
      record = account.signing_requests.find_by(docrunner_packet_id: packet['id'].to_s) or return :no_record

      case event
      when 'Packet.Sent' then Signing.apply(record, 'sent', at: packet['sent_at'])
      when 'Submission.Opened', 'Submitter.Opened' then Signing.apply(record, 'viewed')
      when 'Submitter.Signed' then Signing.apply(record, 'awaiting_signatures', signers: Array(data['submitters']))
      when 'Packet.Voided' then Signing.apply(record, 'voided')
      when 'Packet.Completed'
        Signing.apply(record, 'complete', at: packet['completed_at'])
        ReadAnswersJob.perform_later(record.id, data) # fetches GET /api/packets/:id if data has no answers
      when 'Submitter.Declined' then record.notes.create!(body: "#{data.dig('submitter', 'name') || 'A signer'} declined to sign.")
      end
      :applied
    end
  end
end

# The one place a status changes, from webhooks and from polling.
module Signing
  ORDER = %w[draft sent viewed awaiting_signatures complete].freeze

  def self.apply(record, status, at: nil, signers: nil)
    record.with_lock do
      forward = status == 'voided' || ORDER.index(status).to_i > ORDER.index(record.signing_status).to_i
      record.signed_line = who_signed(signers) if signers.present?
      record.signing_status = status if forward && record.signing_status != 'voided'
      record.save! if record.changed?
    end
  end

  # "Alex Customer signed. Waiting on Sam Customer." (the first party first, then your countersigner)
  def self.who_signed(submitters)
    done, open = submitters.partition { |s| s['completed_at'].present? }
    return nil if done.empty?

    first_role = open.reject { |s| s['role'] == 'pm' } # pm: the slot this app uses for its countersigner
    next_up = first_role.any? ? first_role.map { |s| s['name'].presence || 'the other signer' } : (open.any? ? ['the countersigner'] : [])
    line = "#{done.map { |s| s['name'].presence || 'Someone' }.to_sentence} signed."
    next_up.any? ? "#{line} Waiting on #{next_up.to_sentence}." : line
  end
end
```

## Node (Express)

```js
import express from 'express'
import crypto from 'node:crypto'

const app = express()
const EVENTS = new Set(['Packet.Sent', 'Packet.Completed', 'Packet.Voided', 'Submission.Opened', 'Submitter.Opened', 'Submitter.Signed', 'Submitter.Declined'])

function validSignature(rawBody, header, secret) {
  if (!secret || !header) return false
  const expected = 'sha256=' + crypto.createHmac('sha256', secret).update(rawBody).digest('hex')
  const a = Buffer.from(expected)
  const b = Buffer.from(String(header).trim())
  return a.length === b.length && crypto.timingSafeEqual(a, b)
}

// express.raw keeps the exact bytes DocRunner signed.
app.post('/hooks/docrunner/:token', express.raw({ type: 'application/json' }), async (req, res) => {
  const account = await db.accounts.findByWebhookToken(req.params.token)
  if (!account) return res.sendStatus(404)
  if (!validSignature(req.body, req.get('X-DocRunner-Signature'), account.docrunnerWebhookSecret)) return res.sendStatus(401)

  let payload
  try { payload = JSON.parse(req.body.toString('utf8')) } catch { return res.sendStatus(400) }
  if (!EVENTS.has(payload.event)) return res.sendStatus(200)
  if (account.docrunnerAccountId == null) await db.accounts.setDocrunnerAccountId(account.id, payload.account_id)
  else if (String(payload.account_id) !== String(account.docrunnerAccountId)) return res.sendStatus(200)

  await db.transaction(async (tx) => {
    // Unique (account_id, delivery_id): a retry of a delivery already applied stops here.
    const fresh = await tx.deliveries.insertIfNew(account.id, payload.delivery_id, payload.event)
    if (!fresh) return
    const packet = payload.data?.packet || {}
    const record = await tx.signingRequests.findByPacketId(account.id, String(packet.id))
    if (!record) return
    await applyEvent(tx, record, payload) // same rules as your polling: forward only
  })
  res.sendStatus(200)
  // Slow work after responding, e.g. reading answers on Packet.Completed.
})
```
