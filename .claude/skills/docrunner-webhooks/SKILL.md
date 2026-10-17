---
name: docrunner-webhooks
description: Receive DocRunner's outgoing webhooks in an app - set up the endpoint and events, verify the X-DocRunner-Signature HMAC, apply each delivery_id once despite retries, match deliveries to the right account and record, map Packet and Submitter events to record status (who signed, who's next, declined, voided, completed), read signer answers on Packet.Completed, and keep polling as a fallback. Use this whenever someone is building or debugging a DocRunner webhook endpoint, handling Packet.Completed or Submitter.Signed, or asking how their app finds out a document was signed, even if they don't say "webhook".
---

# DocRunner webhooks

Webhooks make status instant and are the only way to know **who** signed
(`Submitter.Signed`) or that someone **declined** (`Submitter.Declined`).
Keep polling as a fallback anyway (`docrunner-packets-api`, step 4): a
delivery can be missed.

Reference: https://developer.docrunner.io/webhooks/outgoing

## 1. Set up the endpoint

In the DocRunner account: **Settings > Developer Tools > Webhooks > New
endpoint**. Paste your URL, add a contact email (DocRunner emails it after
5 failed attempts), and tick only the events you handle. For a signing
flow:

```
Packet.Sent  Packet.Completed  Packet.Voided
Submission.Opened  Submitter.Opened  Submitter.Signed  Submitter.Declined
```

DocRunner shows the **secret once**. Store it encrypted, per account, and
never print or log it. Use DocRunner's **Send test** button and check for a
200 in its delivery list.

**Multi-tenant apps:** give each account its own URL with a random token
(`/hooks/docrunner/<token>`). The token only picks the account; the
signature is what proves the delivery is real.

## 2. Verify, dedupe, then apply

Every delivery has the same envelope:

```json
{ "event": "Submitter.Signed", "delivery_id": "8a7b6c5d-...", "occurred_at": "...", "account_id": 7,
  "data": { "packet": { "id": 123, "status": "awaiting_signatures", "sent_at": "...", "completed_at": null },
            "submission": { ... }, "submitter": { ... }, "submitters": [ ... ] } }
```

Handle it in this order:

1. **Verify the signature.** `X-DocRunner-Signature` is `sha256=<hex>`, the
   HMAC-SHA256 of the **raw body** with the endpoint's secret. Compare in
   constant time. Wrong or missing: 401. Unknown token: 404. Read the raw
   body before any JSON parsing; re-serialized JSON won't match.
2. **Check the account.** The API doesn't say which account a key belongs
   to, so remember `account_id` from the first verified delivery (or pin it
   at setup) and ignore deliveries from any other account.
3. **Apply each `delivery_id` once.** DocRunner retries anything that isn't a
   2xx (30 s, 2 min, 10 min, 1 h, 6 h). Record the `delivery_id` in the
   **same database transaction** as the change: if applying fails, the
   retry finds no record and applies it again. A week of ids is plenty.
4. **Find the record by packet id** (`data.packet.id`), scoped to that
   account. No record: return 200 and log it (it's someone else's packet).
5. **Return 200 quickly.** Do slow work (fetching the packet, emails) after
   the response or in a job, so DocRunner doesn't time out and retry.

Accept and ignore events you don't handle (return 200).

`references/handler.md` has the handler in Ruby (Rails) and Node (Express).

## 3. What each event should do

| Event | On your record |
|---|---|
| `Packet.Sent` | Status "Sent", sent date from `data.packet.sent_at`. |
| `Submission.Opened`, `Submitter.Opened` | "Opened". |
| `Submitter.Signed` | Who signed and who's next, from `data.submitters` (each has `name`, `role`, `completed_at`). For example: every customer signer is done and your countersigner isn't, so "Waiting on Jordan" and tell Jordan it's their turn; otherwise "Partly signed". |
| `Packet.Completed` | "Complete", signed date from `completed_at` (in the account's time zone), then read the signer answers (below). |
| `Packet.Voided` | "Voided"; step your record back to before sending. |
| `Submitter.Declined` | A plain note with who declined (`data.submitter.name`). Don't move anything else; a person decides what's next. |

**Status only moves forward.** Deliveries and polling arrive out of order,
so a late `Packet.Sent` must not undo `awaiting_signatures`. Put every
status change, from webhooks and from polling, through **one function** that
holds that rule, so a change is recorded once whichever told you first.

Building the "who signed" line from `submitters`:

```
signed  = submitters with completed_at
waiting = submitters without, signers of the first role first, then the countersigner
"Alex Customer signed. Waiting on Sam Customer."   /   "Alex Customer and Sam Customer signed. Waiting on your countersigner."
```

## 4. Signer answers on Packet.Completed

`submitted_fields` (what each signer typed) is on `GET /api/packets/:id`.
It may or may not be on the `Packet.Completed` delivery, so look on
`data.submitted_fields` and `data.packet.submitted_fields` first, and fetch
the packet when neither has the role you need. Log which one you used
("answers carried by the webhook" / "read from GET /api/packets/:id"); the
first real signing tells you.

Then read them the way `docrunner-packets-api` (step 5) describes: filter
by role, drop signatures and W-9 values, merge duplicates, allow-list.

## 5. Test it

- Unit-test the signature check with a known body, secret and header, and a
  tampered body.
- Replay the same delivery twice and check the record changed once.
- Replay `Packet.Sent` after `Submitter.Signed` and check nothing moved back.
- Keep a real `Packet.Completed` payload and a real `GET /api/packets/:id`
  response (test values only) as fixtures.
