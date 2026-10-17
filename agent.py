"""Create and send a DocRunner test packet from a plain-English onboarding request.

Usage:
    python3 agent.py "Onboard Acme Co for the statement of work. Contact Dana Lee,
    dana@acme.example. Start October 1, 2026, fee $1200, deposit $300, paid monthly."

Claude reads the request and fills the packet's variables. This script maps the
client to the "owner" role and the agency countersigner to the "pm" role, checks
the packet, then creates and sends it. Signers are emailed only through DocRunner's
test mode, so every signer address is replaced with TEST_SIGNER_EMAIL.
"""
import datetime
import json
import os
import sys
from pathlib import Path

import anthropic

import docrunner_client as dr

ROOT = Path(__file__).resolve().parent
PACKET = json.loads((ROOT / "packet_catalog.json").read_text())["packet_template"]
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
CLIENT_ROLE = "owner"
COUNTERSIGNER_ROLE = "pm"
SIGNING_EMAIL_BODY = "Please review and sign."


class OnboardingError(Exception):
    """A problem to show the person in plain words."""


def packet_variables():
    """The variables the app fills, merged from every document in the packet.

    A name that appears in more than one document is one variable. Signers fill
    the other fields, so only type "variable" fields are read here.
    """
    merged = {}
    for path in PACKET["fields_files"]:
        for field in json.loads((ROOT / path).read_text()):
            if field.get("type") == "variable":
                merged.setdefault(field["name"], field)
    return list(merged.values())


def fill_packet_tool():
    variables = {}
    for field in packet_variables():
        name = field["name"]
        if field.get("variant") == "checkbox":
            variables[name] = {"type": "boolean", "description": f"True only when this option applies: {name}."}
        else:
            variables[name] = {
                "type": "string",
                "description": f"Value for {name}, as it should print. Empty string when the request does not give it.",
            }
    return {
        "name": "fill_packet",
        "description": "Fill the client details and packet variables from the request.",
        "input_schema": {
            "type": "object",
            "properties": {
                "client_name": {"type": "string", "description": "The client's full name. Empty string when missing."},
                "client_email": {"type": "string", "description": "The client's email. Empty string when missing."},
                "variables": {"type": "object", "properties": variables, "required": list(variables)},
            },
            "required": ["client_name", "client_email", "variables"],
        },
    }


def ask_claude(claude, tool, system, request_text):
    """Ask Claude to answer through one tool and return that tool's input.

    The model rejects forced tool choice, so the prompt asks for the tool and
    the reply is checked for a tool call.
    """
    response = claude.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=f"{system}\nAnswer by calling the {tool['name']} tool.",
        tools=[tool],
        messages=[{"role": "user", "content": request_text}],
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == tool["name"]:
            return block.input
    text = " ".join(b.text for b in response.content if b.type == "text").strip()
    raise OnboardingError(f"Claude did not call the {tool['name']} tool. It replied: {text or '(no text)'}")


def build_variables(values):
    """Return (variables, missing) for the packet, from Claude's answers.

    Values are sent without commas, so "$8,500" goes out as "$8500" and
    "November 3, 2026" as "November 3 2026".
    """
    optional = set(PACKET.get("optional_variables", []))
    variables, missing = {}, []
    groups = {}
    for field in packet_variables():
        name = field["name"]
        key = dr.variable_name(name)
        if field.get("variant") == "checkbox":
            groups.setdefault(name.rsplit("_", 1)[0], []).append(name)
            variables[key] = "true" if values.get(name) is True else ""
            continue
        text = str(values.get(name) or "").replace(",", "").strip()
        if not text and name not in optional:
            missing.append(name)
        variables[key] = text
    # Checkboxes in one group are options of one choice: exactly one must be ticked.
    for group, names in groups.items():
        if not any(values.get(n) is True for n in names):
            missing.append(f"one option for {group.replace('_', ' ')}")
    return variables, missing


NOT_SIGNING_LINKS = {"signed_document_url", "certificate_url"}


def find_signing_links(data, trail=(), under_sign=False):
    """Collect every signing URL in a DocRunner response, with the path to it.

    A URL counts when a key above it contains "sign", such as
    packet.success_info.test_signing_urls (a list of URLs). Download links for
    finished packets are skipped.
    """
    links = []
    if isinstance(data, dict):
        for key, value in data.items():
            if key in NOT_SIGNING_LINKS:
                continue
            links += find_signing_links(value, trail + (key,), under_sign or "sign" in key)
    elif isinstance(data, list):
        for index, value in enumerate(data):
            links += find_signing_links(value, trail + (str(index),), under_sign)
    elif isinstance(data, str) and under_sign and data.startswith("http"):
        links.append((".".join(trail), data))
    return links


def check_roles(template):
    """Refuse to create a packet that can never complete for lack of a signer slot."""
    roles = set()
    for role in template.get("recipient_roles", []):
        roles.add(role if isinstance(role, str) else role.get("key") or role.get("role") or role.get("name"))
    if not roles:
        raise OnboardingError("DocRunner did not list the packet template's roles. Check the template in DocRunner.")
    missing = {CLIENT_ROLE, COUNTERSIGNER_ROLE} - roles
    if missing:
        raise OnboardingError(
            f"The packet template needs roles {', '.join(sorted(missing))}. Add them in DocRunner first."
        )


def run(request_text):
    if not PACKET.get("packet_template_id"):
        raise OnboardingError("Set packet_template_id in packet_catalog.json to the DocRunner packet template id.")
    claude = anthropic.Anthropic()
    today = datetime.date.today().strftime("%B %d %Y").replace(" 0", " ")

    answers = ask_claude(
        claude,
        fill_packet_tool(),
        f"You fill onboarding paperwork for a services agency. Today is {today}. "
        "Copy values from the request. Format dates as November 3 2026 and money as $8500. "
        "Never use commas in any value. "
        "Use an empty string for any text value the request does not give, and never invent one. "
        "For checkbox fields, set true only on the option the request chooses, and false on the others.",
        request_text,
    )
    client_name = answers["client_name"].strip()
    client_email = answers["client_email"].strip()
    if not client_name or "@" not in client_email:
        raise OnboardingError("Add the client's full name and email address to the request.")

    countersigner_name = os.environ.get("AGENCY_COUNTERSIGNER_NAME", "").strip()
    countersigner_email = os.environ.get("AGENCY_COUNTERSIGNER_EMAIL", "").strip()
    if not countersigner_name or "@" not in countersigner_email:
        raise OnboardingError("Set AGENCY_COUNTERSIGNER_NAME and AGENCY_COUNTERSIGNER_EMAIL in .env.")

    test_email = os.environ.get("TEST_SIGNER_EMAIL", "").strip()
    if "@" not in test_email:
        raise OnboardingError("Set TEST_SIGNER_EMAIL in .env. Test packets send signers to that address.")

    variables, missing = build_variables(answers["variables"])
    if missing:
        names = ", ".join(m.replace("_", " ") for m in missing)
        raise OnboardingError(f"Fill in these first: {names}.")

    template = dr.get_packet_template(PACKET["packet_template_id"])
    check_roles(template)

    company = variables.get("client_company_name") or client_name
    packet = dr.create_packet({
        "packet_template_id": int(PACKET["packet_template_id"]),
        "packet_name": f"{PACKET['title']}, {company}",
        "roles": {
            CLIENT_ROLE: [{"name": client_name, "email": test_email}],
            COUNTERSIGNER_ROLE: [{"name": countersigner_name, "email": test_email}],
        },
        "variables": variables,
    })
    packet_id = packet.get("id")
    if not packet_id:
        raise OnboardingError("DocRunner did not return a packet id.")
    sent = dr.send_packet(packet_id, SIGNING_EMAIL_BODY)

    print(f"Created and sent packet {packet_id} in test mode.")
    print(f"Client {client_name} signs as owner. {countersigner_name} signs as pm.")
    print(f"Real signer addresses were replaced with {test_email} for this test.")
    links = find_signing_links(sent)
    source = "the send response"
    if not links:
        links = find_signing_links(dr.get_packet(packet_id))
        source = f"GET /api/packets/{packet_id}"
    if links:
        print(f"Signing links (from {source}):")
        for label, url in links:
            print(f"  {label}: {url}")
        if len(links) < 2:  # one link per signer, and this packet has two signers
            print("DocRunner lists only the signer who is up next. The next link appears after that signer signs.")
    else:
        print(
            f"No signing links came back from the send response or from GET /api/packets/{packet_id}. "
            "Open the packet in DocRunner to get them, and check that the packet template is in Test Mode."
        )


def main(argv):
    if len(argv) < 2:
        print('Usage: python3 agent.py "onboarding request in plain English"', file=sys.stderr)
        return 2
    dr.load_env()
    try:
        run(" ".join(argv[1:]).strip())
    except Exception as err:
        # Always show the exception type and message, so the real cause is visible.
        print(f"Stopped: {type(err).__name__}: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
