"""Small DocRunner API client shared by agent.py and webhook_server.py.

The API key goes only in the X-API-Key header. Error messages never include it.
"""
import json
import os
import re
import socket
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = os.environ.get("DOCRUNNER_API_URL", "https://app.docrunner.io/api").rstrip("/")


class DocRunnerError(Exception):
    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status


def load_env(path=ROOT / ".env"):
    """Read KEY=value lines from .env. Real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.split("#", 1)[0].strip().strip("'\""))


def variable_name(name):
    """How DocRunner saves a variable name: snake_case, repeated underscores collapsed."""
    text = str(name).strip().replace("#", "_num_")
    text = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", text)
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).lower()
    return re.sub(r"_+", "_", text).strip("_")


def _message(code, said):
    if code == 401:
        return "DocRunner did not accept the key. It needs reconnecting."
    if code == 404:
        return said or "DocRunner could not find that."
    if code in (406, 422):
        return f"DocRunner said: {said or 'it could not do that'}."
    return f"DocRunner didn't answer ({code}). Try again in a minute."


def _call(method, path, body=None):
    key = os.environ.get("DOCRUNNER_API_KEY", "").strip()
    if not key:
        raise DocRunnerError("DocRunner is not connected yet. Set DOCRUNNER_API_KEY in .env.")
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"X-API-Key": key, "Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as err:
        try:
            parsed = json.loads(err.read() or b"{}")
        except ValueError:
            parsed = {}
        said = str(parsed.get("error", "")).strip() if isinstance(parsed, dict) else ""
        raise DocRunnerError(_message(err.code, said), err.code) from None
    except (urllib.error.URLError, socket.timeout, OSError):
        raise DocRunnerError("DocRunner didn't answer. Try again in a minute.") from None


def get_packet_template(template_id):
    return _call("GET", f"/packet_templates/{int(template_id)}").get("packet_template", {})


def create_packet(packet):
    packet = dict(packet)
    packet["variables"] = {variable_name(k): str(v) for k, v in packet.get("variables", {}).items()}
    return _call("POST", "/packets", {"packet": packet}).get("packet", {})


def send_packet(packet_id, email_body):
    # The API needs a non-empty packet object, so the body goes inside it.
    body = {"packet": {"send_email_body": email_body}}
    return _call("POST", f"/packets/{int(packet_id)}/send", body).get("packet", {})


def get_packet(packet_id):
    return _call("GET", f"/packets/{int(packet_id)}").get("packet", {})


def download_signed_pdf(url, dest):
    """Save the signed PDF. The link is a plain URL, so the API key is never sent to it."""
    if not str(url).startswith("https://"):
        raise DocRunnerError("The signed PDF link is not an HTTPS link.")
    request = urllib.request.Request(url, headers={"Accept": "application/pdf"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            content = response.read()
    except (urllib.error.URLError, socket.timeout, OSError):
        raise DocRunnerError("Could not download the signed PDF. Try again in a minute.") from None
    if not content.startswith(b"%PDF"):
        raise DocRunnerError("The download was not a PDF.")
    dest.parent.mkdir(exist_ok=True)
    partial = dest.with_suffix(".part")
    partial.write_bytes(content)
    partial.replace(dest)
