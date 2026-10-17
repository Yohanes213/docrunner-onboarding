# DocRunner API: known gaps and workarounds (October 2026)

Found while building production integrations. Check
https://developer.docrunner.io before relying on any of these; some may be
fixed by the time you read this.

| Gap | What happens | Workaround |
|---|---|---|
| Role keys | `POST /api/packets` accepts only `owner`, `tenant` and `pm` in `roles`. Other keys are dropped silently. | Treat them as three fixed signer slots. Map your own signer types onto them once (for example customer = `owner`, second party = `tenant`, your countersigner = `pm`) and use those keys on every packet template. |
| Missing role on a packet | A packet created without a signer for one of the template's roles never reaches `complete`. | Always send at least one signer for every role on the template. Read `recipient_roles` from `GET /api/packet_templates/:id` and check before you create. |
| Send body | `POST /api/packets/:id/send` fails without a non-empty `packet` object. | Always send `{ "packet": { "send_email_body": "..." } }`. |
| Variable name normalization | Names are saved in snake_case with repeated underscores collapsed. A value sent under the un-normalized name is ignored. | Normalize keys before sending (see `docrunner-packets-api`). |
| Choosing documents per packet | A packet created by the API includes every document marked "included by default". | Make a second packet template that adds the optional document (for example a state-specific disclosure or an extra consent form) and pick the template in your app. |
| Who signed | `GET /api/packets/:id/status` only says `awaiting_signatures`. | The `Submitter.Signed` webhook names the signer. |
| Your own reference on a packet | `metadata` isn't accepted on create. | Store DocRunner's packet `id` on your record and look records up by it. |
| Signed PDF | `signed_document_url` is a plain link, filled once complete; it isn't fetched with the API key. | Link to it, or download it when `Packet.Completed` arrives. |
| Template fields | There's no published API to write a template's fields. | `docrunner-template-mapping` places them through the template editor's own save request, in your signed-in browser on your account (backup first). It isn't a published API, so it may change with the editor. |
| Sensitive values in responses | `submitted_fields` returns everything signers typed, including tax-form fields (a W-9's SSN and EIN, for example), to anyone holding an API key on the account. | Drop sensitive fields and anything that looks like a tax ID on read; never log raw responses. |
| Archive and restore | These are `GET` requests that change state. | Don't let prefetchers or crawlers hit them. |
| Account behind a key | The API doesn't say which account a key belongs to. | Remember `account_id` from the first verified webhook delivery and ignore deliveries from other accounts. |
