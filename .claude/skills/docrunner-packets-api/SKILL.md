---
name: docrunner-packets-api
description: Create, send, follow and read back DocRunner signing packets from any app - building the create payload (roles, variables, checkbox values), normalizing variable names, a safe test mode, mapping packet statuses to your records, and turning submitted_fields (what each signer typed) into clean values in your app while dropping tax IDs and other sensitive data. Use this whenever someone is calling the DocRunner API (api/packets, packet_templates), adding an e-signature step to an app or workflow, reading signer answers or submitted_fields, or debugging why a value didn't show on the document, even if they just say "send it for signing" or "get the answers out of DocRunner".
---

# DocRunner packets API

Base URL `https://app.docrunner.io/api`; the key goes in the `X-API-Key`
header and nowhere else (never in a URL, an error message or a log).
Reference: https://developer.docrunner.io/api/packets. Gaps and
workarounds: `KNOWN-ISSUES.md` in this packet.

## The flow

```
GET  /api/packet_templates/:id   check the template's roles once, at setup
POST /api/packets                create a draft (roles + variables)
POST /api/packets/:id/send       send it (DocRunner emails the signers)
     webhooks + GET /api/packets/:id/status   follow it
GET  /api/packets/:id            read submitted_fields once it's complete
POST /api/packets/:id/void       cancel it
```

Keep DocRunner's packet `id` on your record: the API doesn't accept your
own reference (`metadata`) on create, so the id is how webhooks and polling
find the record again.

## 1. Check the template at setup

Read `recipient_roles` from `GET /api/packet_templates/:id` when an account
is connected, and refuse to go on if a role you'll send is missing.

- **Role keys are three fixed slots: `owner`, `tenant` and `pm`.** Other
  keys are dropped silently, whatever your signers are called. Map your
  signer types onto them once, document the mapping, and use it on every
  packet template. For example:

  | Your signer | Role key |
  |---|---|
  | The customer (one or more) | `owner` |
  | A second party (co-signer, guarantor, partner company) | `tenant` |
  | Your company's countersigner | `pm` |

- A packet created **without a signer for one of the template's roles never
  reaches `complete`**. Send at least one signer per role.

Also compare the template's variables with the ones your app sends, and
list any your app doesn't fill, so a missing value is caught at setup and
not on a signed document.

## 2. Create the packet

```json
POST /api/packets
{
  "packet": {
    "packet_template_id": 42,
    "packet_name": "Services agreement, Acme Co",
    "roles": {
      "owner": [{ "name": "Alex Customer", "email": "alex@example.com" }],
      "pm":    [{ "name": "Jordan Rep", "email": "jordan@yourcompany.example" }]
    },
    "variables": {
      "customer_name": "Acme Co",
      "contract_start_on": "October 1, 2026",
      "monthly_fee": "$1,200",
      "plan_tier_premium": "true",
      "plan_tier_basic": ""
    }
  }
}
```

Build `variables` like this:

- **Every value is a string.** Format dates and money the way the document
  should print them ("October 1, 2026", "10%", "$1,200").
- **Normalize every key** the way DocRunner saves names: snake_case,
  repeated underscores collapsed. A value under an un-normalized key is
  ignored without an error. In Ruby:
  `name.to_s.strip.gsub('#', '_num_').underscore.parameterize(separator: '_')`.
  In JavaScript, see `references/client.md`.
- **Checkboxes your app ticks:** `"true"` for the chosen option, `""` for
  every other option of that field (send them all, so a revised packet never
  keeps a stale tick).
- **Constants** (your company's name, address, phone) come from settings,
  not the PDF.
- **Check values with commas on a test packet.** On one account (October
  2026) a value with commas printed only its last part ("Springfield, IL
  62704" came out as "62704"). If yours does the same, send address parts
  as separate variables or leave the commas out.
- **Computed values** (a total from a quantity and a price, "TBD" when
  there's no number yet) are computed in your app and sent like any other
  variable.

**Refuse to create the packet when something it needs is blank**, and say
which fields in plain words ("Fill in Start date and Monthly fee first"). A
signed document with a blank price is much harder to fix than a draft that
didn't go out.

## 3. Send, and test mode

```json
POST /api/packets/:id/send
{ "packet": { "send_email_body": "Please review and sign." } }
```

The `packet` object is required even though only the email body is in it.

**DocRunner emails the signers itself**, so your app's own "don't email
real people in test" guard doesn't cover it. Before creating a packet in
any non-production setting, replace every signer's email with your own
test address, and note that on the record ("Test mode: sent to you instead
of alex@example.com"). DocRunner's own test-mode packets send no email and
return `test_signing_urls` instead.

## 4. Follow the status

| `status` | Meaning |
|---|---|
| `draft` | Created, not sent |
| `sent` | Sent to signers |
| `viewed` | Someone opened it |
| `awaiting_signatures` | Someone signed, others haven't |
| `complete` | Everyone signed |
| `voided` | Cancelled |

- **Move your record forward only.** Webhooks and polling can arrive out of
  order; never let a late `sent` overwrite `awaiting_signatures`.
- The status endpoint says *that* someone signed, never *who*. The
  `Submitter.Signed` webhook names them (`docrunner-webhooks`), which is
  what lets you say "Alex signed. Waiting on your countersigner."
- Poll `GET /api/packets/:id/status` for packets not yet complete or voided
  as a fallback (every 3 minutes without webhooks, every 15 with them). A
  404 means the packet is gone: treat it as voided.
- Run webhooks and polling through **one function** that applies a status to
  a record, so the rules live in one place and a change is recorded once.

## 5. Read what the signers typed

Once complete, `GET /api/packets/:id` carries `submitted_fields`: one entry
per field on the packet, every signer's, in document order.

```json
{ "name": "billing_email", "type": "text", "value": "ap@acme.example",
  "template_id": 85, "signer": { "name": "Alex Customer", "email": "alex@example.com", "role": "owner" } }
```

What to know:

- **Every signer's fields are in one list.** Filter by `signer.role`.
- **Checkboxes** are `true` / `false`. **Signatures** carry the typed name,
  not an image. Empty fields are `null`.
- **A field placed twice comes back twice**, and the copies can differ (one
  filled, one blank). Take the first filled-in value; for a checkbox, a
  ticked copy beats an unticked one.
- **Everything typed comes back, tax forms included** (for example a W-9's
  SSN and EIN). Never store what you don't need.

`scripts/read_answers.py` does all of this: filter to one role, drop
signatures, tax-form fields (by name prefix) and anything that looks like
an SSN or EIN, merge duplicates, keep only the fields you list, and label
them. Run it on a saved response to see what your app would keep:

```
python3 scripts/read_answers.py packet.json --role owner --fields fields.json
```

`scripts/example_packet.json` and `scripts/example_fields.json` show the
shapes, including a duplicated field, an SSN on a tax form, a tax ID typed
into a notes box, a password typed into an access-notes box and the
countersigner's signature. Try it on those first.

Then port the same steps into your app (the script is short on purpose).
Rules worth keeping in your port:

- **Allow-list, don't block-list.** Keep only names you've mapped; a new
  field on the template then can't leak into your app unnoticed.
- **Guard free-text boxes that might hold secrets** (access notes, door or
  gate codes, passwords, account numbers): if the value has 3 or more digits
  in a row, store a note to read it in DocRunner instead of the value.
- **Never log the raw response.** It can hold a tax ID.
- **Re-reading must be safe**: overwrite your stored answers, don't append,
  and don't overwrite fields a person already filled in on your side.
- **A packet with no answers yet** (completed before the account had this,
  or the field list is empty) should say "not read yet" and be re-readable
  later, not fail.

## 6. Errors

| Code | What to tell the person |
|---|---|
| 401 | The key wasn't accepted; it needs reconnecting. |
| 404 | DocRunner couldn't find that (show its `error` if present). |
| 406, 422 | "DocRunner said: ..." with its `error` message. |
| Other, timeout | "DocRunner didn't answer. Try again in a minute." |

`references/client.md` has a small client in Ruby and JavaScript with
these messages, the key kept out of errors and logs, and timeouts set.
