# DocRunner onboarding

A software agency onboards a new client with one plain-English sentence. Claude reads the request and fills the variables of the agency's onboarding packet. The packet goes to the client for signature through DocRunner. The client signs first, then the agency countersigns. A small webhook server logs each event and saves the signed PDF.

```
"Onboard Acme Corp. Contact Jane Doe ..."
        │
   agent.py ── Claude fills the variables, then:
        │         GET  /api/packet_templates/57
        │         POST /api/packets            client → owner, agency countersigner → pm
        │         POST /api/packets/:id/send   test mode: signing links come back
        ▼
   DocRunner ── Packet.Sent · Submitter.Opened · Submitter.Signed · Packet.Completed
        │
   webhook_server.py ── verifies the signature, logs the event, saves signed/packet-<id>.pdf
```

## What's in the repo

| Path | What it is |
|---|---|
| `agent.py` | Turns a request into a packet, sends it in test mode, prints the signing links |
| `webhook_server.py` | Receives DocRunner webhooks at `POST /hooks/docrunner`, verifies `X-DocRunner-Signature`, logs events, saves the signed PDF on `Packet.Completed` |
| `docrunner_client.py` | Small DocRunner API client shared by both scripts. The key goes only in the `X-API-Key` header |
| `packet_catalog.json` | The packet template id (57) and the field lists the agent fills |
| `docrunner-templates/<doc>/` | Per document: `build_fields.py` (field spec), `template_fields.json` (field list), `place_fields.js` (loader for the template editor) |
| `PDFs/` | The three source documents |
| `.claude/skills/` | DocRunner skills for Claude Code: template mapping, the API, webhooks, setup |
| `docs/docrunner-skills-packet.md` | The original readme from the DocRunner skills packet |
| `KNOWN-ISSUES.md` | DocRunner API gaps and the workaround for each |

## Requirements

- Python 3.9 or newer.
- A DocRunner account and an API key.
- An Anthropic API key.
- ngrok or Cloudflare Tunnel, so DocRunner can reach your machine for webhooks.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then fill it in
```

Fill in these values in `.env`. Never commit `.env`. It is listed in `.gitignore`.

| Variable | Required | What it is |
|---|---|---|
| `DOCRUNNER_API_KEY` | yes | DocRunner: Settings > Developer Tools > API Keys |
| `DOCRUNNER_WEBHOOK_SECRET` | yes | Displayed once by DocRunner |
| `ANTHROPIC_API_KEY` | yes | Your Anthropic API key |
| `AGENCY_COUNTERSIGNER_NAME` | yes | The agency's countersigner, who signs as `pm` |
| `AGENCY_COUNTERSIGNER_EMAIL` | yes | The countersigner's email |
| `TEST_SIGNER_EMAIL` | yes | Every signer's address is replaced with this one on test packets |
| `ANTHROPIC_MODEL` | no | Overrides the Claude model. The default is `claude-sonnet-5-5` |
| `DOCRUNNER_ACCOUNT_ID` | no | Ignores webhooks from any other DocRunner account |
| `WEBHOOK_PORT` | no | Webhook server port. The default is 8000 |

## 1. Check the packet template

Packet template 57 in DocRunner is already set up for this app. It is in Test Mode and has the `owner` and `pm` roles. To check it again, export the key from `.env` and run the read-only check:

```bash
export DOCRUNNER_API_KEY=$(grep '^DOCRUNNER_API_KEY=' .env | cut -d= -f2-)
python3 .claude/skills/docrunner-setup/scripts/check_packet_template.py 57 --roles owner,pm
```

Exit code 0 means the template is ready for the API. Exit code 1 means a problem.

The template holds the statement of work and the mutual NDA. The check lists no IP assignment variables, so make sure that the IP assignment is on the template in DocRunner before you rely on it.

## 2. Place the template fields (only for a new template)

Skip this step for template 57. Use this step to build a new template.

1. In DocRunner, go to **Doc Templates > New**. Upload each PDF in `PDFs/` as its own document template.
2. In Claude Code, use the `docrunner-template-mapping` skill. Ask it to map the fields of each PDF. The client signs as **Owner**, and the agency countersigns as **PM** with signing order 2. The skill writes `template_fields.json` and `place_fields.js` in `docrunner-templates/<doc>/`.
3. For each document template, open **Edit fields**, open the browser console, paste that document's `place_fields.js`, and press Enter. The loader downloads a backup first, then places the fields and signers.
4. Go to **Packet Templates > New**. Add the documents in order. Check that the roles are `owner` and `pm`, then switch the template to **Test Mode**.

To regenerate a loader from its field list, run:

```bash
python3 .claude/skills/docrunner-template-mapping/scripts/make_loader.py docrunner-templates/01_statement_of_work/template_fields.json --slot S1="Owner" --slot CO="PM:2" > place_fields.js
```

## 3. Set up the webhooks

Start the webhook server in one terminal, and the tunnel in another:

```bash
python3 webhook_server.py          # listens on port 8000
ngrok http 8000                    # gives you a public address
```

In DocRunner, go to **Settings > Developer Tools > Webhooks > New endpoint**:

- URL: `https://<your-ngrok-host>/hooks/docrunner`
- Events: `Packet.Sent`, `Submitter.Opened`, `Submitter.Signed`, `Packet.Completed`
- Copy the secret into `DOCRUNNER_WEBHOOK_SECRET` in `.env`. Restart the server. Then press **Send test**.

Logs go to the console and to `logs/webhook_events.log`. Signed PDFs go to `signed/`, named `packet-<id>.pdf`.

## 4. Create and send a packet

Run the agent with the request in quotes:

```bash
python3 agent.py "Onboard Acme Corp. Contact Jane Doe, jane@acme.test. Mobile app MVP for 8500 dollars starting November 3, about 6 weeks, half up front and half on delivery. Scope: build the iOS and Android MVP. The NDA starts October 17 2026 and lasts 2 years."
```

The request must include:

- The client's name and email.
- A scope of work.
- The NDA's effective date.
- The NDA's term in years.

If a value is missing, the agent stops and names it. It creates no packet until every required value is present.

When the agent succeeds, it prints the packet id and the signing links from the send response. The send response lists only the signer who is up next. The client signs first, so the countersigner's link appears after the client signs. Open the client's link to sign. The webhook terminal logs each event. DocRunner then sends `Packet.Completed`, and the server saves the signed PDF to `signed/`.

## Test mode

The packet template is in DocRunner Test Mode, so DocRunner sends no email. As a second guard, the agent replaces every signer's email with `TEST_SIGNER_EMAIL`.

## Notes

- **Blank values:** the agent refuses to create a packet while a required value is blank, and it names the missing values.
- **No commas in values:** values go out without commas, such as `$8500` and `November 3 2026`. Commas are also removed from text such as the scope of work. DocRunner can drop text after a comma. See the DocRunner packets API skill in `.claude/skills/docrunner-packets-api/`.
- **Role keys:** DocRunner accepts only `owner`, `tenant` and `pm`. Here, `owner` is the client and `pm` is the agency's countersigner.
- **Webhook path:** the path has no token. Set `DOCRUNNER_ACCOUNT_ID` to ignore deliveries from other DocRunner accounts.
- **Download on completion:** the server downloads the signed PDF before it replies. If the download fails, it replies with 500, so DocRunner retries the delivery.

## Known limits

- The signed PDF download has not been tested against a live completed packet.
- The send response lists only the signer who is up next. The countersigner's link appears after the client signs.
- The check does not show the IP assignment on packet template 57. Open the template in DocRunner to see whether it is there.
