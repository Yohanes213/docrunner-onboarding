# DocRunner skills packet

Four Claude Code skills that take a developer from a new DocRunner account
to signed documents flowing back into their app, plus a list of known API
gaps. The template skill was tested end to end on live DocRunner
(October 2026): a 2-page agreement went from PDF to 19 placed fields, two
signers, without touching the editor by hand. They work for any document that needs signing: service
agreements, employment and contractor paperwork, sales contracts, consent
and intake forms, vendor onboarding, NDAs. They come from production
integrations, including a 31-page agreement with nearly 200 fields, two
signers on one side and a countersigner on the other.

API reference: https://developer.docrunner.io (base URL
`https://app.docrunner.io/api`, key in the `X-API-Key` header).

## What's inside

| Skill | Use it when you're... |
|---|---|
| `docrunner-setup/` | Starting out, or going live. The order to do everything in, the steps that happen in the DocRunner app (API key, uploading the PDF, the packet template, test mode), a script that checks a packet template is ready for your app, the test loop and a go-live checklist. **Start here.** |
| `docrunner-template-mapping/` | Turning a PDF into a DocRunner template, end to end: Claude finds every blank in the PDF, builds the field list (what your app fills, what each signer fills), and places the fields in your template, with a backup first. No dragging fields by hand. |
| `docrunner-packets-api/` | Creating and sending packets from your app, following their status, and reading what each signer typed back into your app (`submitted_fields`), without keeping sensitive values. |
| `docrunner-webhooks/` | Receiving DocRunner's webhooks: verifying the signature, applying each delivery once, mapping events to your records, and keeping a polling fallback. |
| `KNOWN-ISSUES.md` | What the API can't do yet and the workaround for each. Read it before you design. |

Each skill folder has a `SKILL.md` (what Claude reads first) and, where
useful, `references/` (longer docs) and `scripts/` (runnable code).

## Install

Copy the four skill folders into your project's `.claude/skills/` (or
`~/.claude/skills/` to have them everywhere):

```
mkdir -p .claude/skills
cp -r docrunner-setup docrunner-template-mapping docrunner-packets-api docrunner-webhooks .claude/skills/
```

Claude Code picks them up on its own when a task matches (for example
"place the fields for this contract PDF in my DocRunner template" or "handle
DocRunner's Packet.Completed webhook"). You can also ask for one by name.

To have Claude place fields in your template itself, give it a browser tool
signed in to your DocRunner account (Claude in Chrome, or Playwright
connected to your browser). Without one, Claude hands you a script to paste
into the browser console on the template's Edit fields page.

The scripts need Python 3 and nothing else, except `find_blanks.py`, which
also needs `pip install pdfplumber`.

## Start to finish

| Step | Where | Skill |
|---|---|---|
| 1. Get the API key | DocRunner: Settings > Developer Tools > API Keys | `docrunner-setup` |
| 2. Upload the PDF as a document template | DocRunner: Doc Templates | `docrunner-setup` |
| 3. Find the blanks, build the fields, place them | Claude + the template's Edit fields page | `docrunner-template-mapping` |
| 4. Build the packet template, switch it to Test Mode | DocRunner: Packet Templates | `docrunner-setup` |
| 5. Check it's ready for your app | `check_packet_template.py` | `docrunner-setup` |
| 6. Create, send and follow packets; read the answers back | Your app | `docrunner-packets-api` |
| 7. Receive webhooks | Your app + Settings > Developer Tools > Webhooks | `docrunner-webhooks` |
| 8. Test loop, then go live | Both | `docrunner-setup` |

Ask Claude "set up DocRunner for this app" and it starts at step 1.

## The ten things worth knowing before you start

1. **Variable names are normalized on save.** DocRunner stores variable
   names in snake_case with repeated underscores collapsed, so
   `plan__tier` becomes `plan_tier`. Normalize the same way before you send
   values, or they never land.
2. **A checkbox variable ticks only on the string `"true"`.** Send `""` for
   the boxes that stay empty.
3. **One variable per option** for anything your app ticks (a choice or a
   multi-select): `<field>_<option>`.
4. **Signature dates fill themselves.** Never mark a `signature_date` field
   required; a required one blocks the signer's Complete button.
5. **Role keys are three fixed slots.** The API accepts only the keys
   `owner`, `tenant` and `pm`, whatever your signers are called. Decide once
   what each slot means in your app (for example `owner` = the customer,
   `tenant` = a second party, `pm` = your countersigner) and use those keys
   on every packet template.
6. **Send needs a body.** `POST /api/packets/:id/send` wants
   `{ "packet": { "send_email_body": "..." } }`.
7. **DocRunner emails signers itself, and a new packet template starts in
   Production.** Switch it to Test Mode before your first packet, and in
   test swap every signer's email for your own: your app's own test-mode
   email guard doesn't cover DocRunner's emails.
8. **Status says *that* someone signed, not who.** The `Submitter.Signed`
   webhook names them. Use webhooks for who; poll status as the fallback.
9. **Signer answers come back as `submitted_fields`** on `GET
   /api/packets/:id`: one entry per field, every signer, with the signer's
   role. Checkboxes are booleans, signatures are the typed name, and a field
   placed twice appears twice.
10. **The API returns every value signers typed, tax forms included** (for
    example a W-9's SSN or EIN). Drop sensitive fields on read and never log
    the raw response.
