# A small DocRunner client

Both versions: the key only in the `X-API-Key` header, variable names
normalized on the way out, plain-language errors, timeouts set, and one
`transport` function so tests can stub the network.

## Ruby (Rails)

```ruby
require 'net/http'

module DocRunner
  BASE = ENV.fetch('DOCRUNNER_API_URL', 'https://app.docrunner.io/api').chomp('/')
  class Error < StandardError
    attr_reader :status
    def initialize(message, status = nil) = (super(message); @status = status)
  end

  module_function

  # How DocRunner saves a variable name: snake_case, repeated underscores
  # collapsed. Send keys the same way or the value never lands.
  def variable_name(name)
    name.to_s.strip.gsub('#', '_num_').underscore.parameterize(separator: '_')
  end

  def packet_template(key, id) = get(key, "/packet_templates/#{id.to_i}")['packet_template'] || {}

  def create_packet(key, packet)
    packet = packet.merge(variables: packet[:variables].to_h.transform_keys { |k| variable_name(k) }) if packet[:variables]
    post(key, '/packets', { packet: packet })['packet'] || {}
  end

  # The API needs a non-empty packet object; the body goes in the invitation email.
  def send_packet(key, id, email_body) = post(key, "/packets/#{id.to_i}/send", { packet: { send_email_body: email_body } })['packet'] || {}
  def status(key, id) = get(key, "/packets/#{id.to_i}/status")['packet'] || {}
  def packet(key, id) = get(key, "/packets/#{id.to_i}")['packet'] || {}
  def void(key, id, reason) = post(key, "/packets/#{id.to_i}/void", { packet: { void_reason: reason } })['packet'] || {}

  def get(key, path) = call(:get, key, path)
  def post(key, path, body) = call(:post, key, path, body)

  def call(method, key, path, body = nil)
    raise Error, 'DocRunner is not connected yet.' if key.to_s.empty?

    code, text = transport(method, URI("#{BASE}#{path}"),
                           { 'X-API-Key' => key, 'Accept' => 'application/json', 'Content-Type' => 'application/json' }, body&.to_json)
    data = (JSON.parse(text.to_s.empty? ? '{}' : text) rescue {})
    return data if code.between?(200, 299)

    said = data.is_a?(Hash) ? data['error'].to_s.strip : ''
    message = case code
              when 401 then 'DocRunner did not accept the key. It needs reconnecting.'
              when 404 then said.empty? ? 'DocRunner could not find that.' : said
              when 406, 422 then "DocRunner said: #{said.empty? ? 'it could not do that' : said}."
              else "DocRunner didn't answer (#{code}). Try again in a minute."
              end
    raise Error.new(message, code)
  end

  # The one place that talks to the network; stub it in tests. Returns [status, body].
  def transport(method, uri, headers, body)
    request = (method == :post ? Net::HTTP::Post : Net::HTTP::Get).new(uri, headers)
    request.body = body if body
    response = Net::HTTP.start(uri.host, uri.port, use_ssl: uri.scheme == 'https', open_timeout: 5, read_timeout: 30) { |http| http.request(request) }
    [response.code.to_i, response.body.to_s]
  rescue Net::OpenTimeout, Net::ReadTimeout, SocketError, Errno::ECONNREFUSED, OpenSSL::SSL::SSLError
    raise Error.new("DocRunner didn't answer. Try again in a minute.", 0)
  end
end
```

## JavaScript (Node 18+)

```js
const BASE = (process.env.DOCRUNNER_API_URL || 'https://app.docrunner.io/api').replace(/\/$/, '')

export class DocRunnerError extends Error {
  constructor(message, status) { super(message); this.status = status }
}

// How DocRunner saves a variable name: snake_case, repeated underscores collapsed.
export function variableName(name) {
  return String(name).trim()
    .replace(/#/g, '_num_')
    .replace(/([a-z\d])([A-Z])/g, '$1_$2')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_|_$/g, '')
}

async function call(method, key, path, body) {
  if (!key) throw new DocRunnerError('DocRunner is not connected yet.')
  let res
  try {
    res = await fetch(BASE + path, {
      method,
      headers: { 'X-API-Key': key, Accept: 'application/json', 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(30000)
    })
  } catch {
    throw new DocRunnerError("DocRunner didn't answer. Try again in a minute.", 0)
  }
  const data = await res.json().catch(() => ({}))
  if (res.ok) return data
  const said = (data && data.error ? String(data.error) : '').trim()
  const message = res.status === 401 ? 'DocRunner did not accept the key. It needs reconnecting.'
    : res.status === 404 ? (said || 'DocRunner could not find that.')
    : [406, 422].includes(res.status) ? `DocRunner said: ${said || 'it could not do that'}.`
    : `DocRunner didn't answer (${res.status}). Try again in a minute.`
  throw new DocRunnerError(message, res.status)
}

export const packetTemplate = async (key, id) => (await call('GET', key, `/packet_templates/${Number(id)}`)).packet_template || {}
export async function createPacket(key, packet) {
  const variables = Object.fromEntries(Object.entries(packet.variables || {}).map(([k, v]) => [variableName(k), String(v ?? '')]))
  return (await call('POST', key, '/packets', { packet: { ...packet, variables } })).packet || {}
}
export const sendPacket = async (key, id, emailBody) => (await call('POST', key, `/packets/${Number(id)}/send`, { packet: { send_email_body: emailBody } })).packet || {}
export const status = async (key, id) => (await call('GET', key, `/packets/${Number(id)}/status`)).packet || {}
export const getPacket = async (key, id) => (await call('GET', key, `/packets/${Number(id)}`)).packet || {}
export const voidPacket = async (key, id, reason) => (await call('POST', key, `/packets/${Number(id)}/void`, { packet: { void_reason: reason } })).packet || {}
```

Check the JavaScript `variableName` against a variable saved in your
template (read it back from `GET /api/packet_templates/:id`) before relying
on it; the Ruby version is the one used in production.
