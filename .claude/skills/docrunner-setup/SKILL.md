---
name: docrunner-setup
description: Set up a DocRunner account for an app integration from scratch and take it live - get the API key, upload a PDF as a document template, name signers so the API can use them, build the packet template (documents, roles, signing order, invitation email, reminders, test mode), check it's ready with a script, run the full test loop, and go through the go-live checklist. Use this first whenever someone is starting a DocRunner integration, asks where to begin, needs a packet_template_id, is wiring e-signature into an app for the first time, or is about to switch from test to production, even if they only ask about one step.
---

# DocRunner setup, start to finish

The other three skills each cover one part. This one is the order to do
them in, plus the steps that only happen in the DocRunner app.

```
1. API key                        (this skill)
2. Document template: upload PDF  (this skill)
3. Fields: find, build, place     docrunner-template-mapping
4. Packet template                (this skill)
5. Check it's ready               (this skill: scripts/check_packet_template.py)
6. Your app: create, send, follow docrunner-packets-api
7. Webhooks                       docrunner-webhooks
8. Test loop, then go live        (this skill)
```

## 1. API key

In DocRunner: **Settings > Developer Tools > API Keys**. One key per account.
It goes in the `X-API-Key` header of every request
(`https://app.docrunner.io/api`).

- Keep it in your secret store or environment, never in code, a URL or a log.
- **Regenerate** gives a new key and the old one stops working at once, so
  update your app in the same minute.
- Each DocRunner account has its own key. If your app serves several
  customers with their own DocRunner accounts, store one key per customer.

## 2. Document template (the PDF)

**Doc Templates > New**: give it a name, choose the PDF, press **Create
Template**.

- One PDF per document template keeps page numbers simple when placing
  fields. Separate documents (an agreement, an addendum, a disclosure) are
  better as separate document templates, bundled in step 4.
- A changed PDF later: upload the new version as a new document template and
  place its fields again (`docrunner-template-mapping` makes that fast), then
  swap it into the packet template. Editing pieces of a live template is
  how stale fields happen.

## 3. Fields

Use `docrunner-template-mapping`: find the blanks, build the field list, and
place the fields on the document template's **Edit fields** page.

**Name the signers for the API.** The packet template's roles come from the
signer names on its documents: a trailing number is dropped and the rest
lowercased, so "Owner 1" and "Owner 2" become role `owner` (up to two
signers) and "PM" becomes `pm`. The API accepts only `owner`, `tenant` and
`pm`, so use those names ("Owner", "Owner 1", "Owner 2", "Tenant",
"Tenant 1", "PM") and decide once what each means in your app (for example
customer = Owner, a second party = Tenant, your countersigner = PM). Use the
same names on every document in a packet so they merge into one role.

**Signing order** is set per signer (same number = sign at the same time,
higher = after). For a countersignature, give your company's signer a
higher number than the customer's.

## 4. Packet template (what your app creates packets from)

**Packet Templates > New Packet Template**:
- **Name** and **Description**.
- **Signing Email Message**: the default text of the invitation email.
- **Category** and **Template Key** (your own label for it, for example
  `services_v2`): optional.
- **Reminders**: "Send first reminder in" N days, and optionally "Repeat
  every" N days, for signers who haven't finished.

Press **Create Packet Template**, then on its page:
- **Add** each document template, in the order signers should see them.
- Check the signer roles it shows (they come from the document templates'
  signers, step 3).
- **Switch to Test Mode.** A new packet template starts in **Production**,
  which emails real signers. In Test Mode no emails go out: sending returns a
  signing link for each signer instead.

Its id (in the page address, `/packet_templates/<id>`) is the
`packet_template_id` your app sends.

**Optional documents** (a disclosure only some packets need): the API can't
add or drop a document per packet yet. Make a second packet template with the
extra document and have your app pick between the two.

## 5. Check it's ready

```
export DOCRUNNER_API_KEY=...
python3 scripts/check_packet_template.py <id> --sends my_variables.txt --roles owner,pm
```

Read only. It shows test mode, each role (and whether the API accepts its
key), every variable the documents expect (checkboxes marked), the
variables your app sends that the template doesn't have (dropped), the ones
it doesn't send (print empty), and any role your app doesn't send (a packet
missing a role never completes). It exits non-zero on a problem, so it can
run in CI before each deploy.

## 6 and 7. Your app

Build creating, sending, following and reading packets with
`docrunner-packets-api`, and the webhook endpoint with `docrunner-webhooks`
(Settings > Developer Tools > Webhooks).

## 8. Test loop, then go live

With the packet template in **Test Mode**:

1. Create a packet from your app with a recognizable value in every variable
   (`T-customer_name`) and your own email for every signer.
2. Send it. The response's `test_signing_urls` has a link for each signer up
   next; open each in turn and sign, typing `T-<field name>` into every
   signer field.
3. Check the signed PDF: every variable printed in the right place, checkbox
   variables ticked as sent, signatures and dates where they belong.
4. Check your app: status moved sent, opened, signed, complete (webhooks and
   the polling fallback), the "who signed" line, and the answers read back
   from `submitted_fields` with nothing sensitive stored.
5. Void one packet and decline one, and check your app handles both.
6. Keep the completed packet's API response and a few webhook payloads as
   test fixtures.

**Go-live checklist:**
- [ ] `check_packet_template.py` passes for every packet template your app uses.
- [ ] The packet template is switched to **Production** (and nothing else
      changed since the test).
- [ ] Your app's own test guard (every signer swapped for your address) is
      off in production only.
- [ ] Webhook endpoint registered in the production account, secret stored,
      **Send test** returns 200.
- [ ] Polling fallback running for packets not complete or voided.
- [ ] Raw API responses and webhook bodies are not logged (they can hold
      tax IDs and anything else signers typed).
- [ ] Someone gets the "delivery failed" email (the webhook contact email).
- [ ] You know where the signed PDF lives for each record
      (`signed_document_url` once complete).
- [ ] Known gaps read: `KNOWN-ISSUES.md`.
