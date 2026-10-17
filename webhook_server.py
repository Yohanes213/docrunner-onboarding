"""Receive DocRunner webhooks at POST /hooks/docrunner and save signed PDFs.

Run with:  python3 webhook_server.py
Listens on WEBHOOK_PORT (default 8000). Logs each event to the console and to
logs/webhook_events.log. Signed PDFs go to signed/.
"""
import hashlib
import hmac
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import docrunner_client as dr

ROOT = Path(__file__).resolve().parent
SIGNED_DIR = ROOT / "signed"
LOG_DIR = ROOT / "logs"
SEEN_FILE = LOG_DIR / "seen_deliveries.json"
WEBHOOK_PATH = "/hooks/docrunner"
MAX_BODY_BYTES = 1_000_000
MAX_SEEN = 5000

log = logging.getLogger("docrunner")
seen_lock = threading.Lock()


def load_seen():
    try:
        return json.loads(SEEN_FILE.read_text())
    except (OSError, ValueError):
        return []


seen = load_seen()
seen_set = set(seen)


def is_seen(delivery_id):
    with seen_lock:
        return delivery_id in seen_set


def remember(delivery_id):
    """Record a delivery id once it has been fully handled, so a retry is skipped."""
    with seen_lock:
        if delivery_id in seen_set:
            return
        seen.append(delivery_id)
        seen_set.add(delivery_id)
        while len(seen) > MAX_SEEN:
            seen_set.discard(seen.pop(0))
        partial = SEEN_FILE.with_suffix(".tmp")
        partial.write_text(json.dumps(seen))
        partial.replace(SEEN_FILE)


def valid_signature(body, header):
    """X-DocRunner-Signature is 'sha256=' plus the HMAC-SHA256 of the raw body."""
    secret = os.environ.get("DOCRUNNER_WEBHOOK_SECRET", "").encode()
    if not secret or not header:
        return False
    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.strip())


def save_signed_pdf(payload):
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    packet = data.get("packet") if isinstance(data.get("packet"), dict) else {}
    packet_id = packet.get("id")
    dest = SIGNED_DIR / f"packet-{packet_id}.pdf"
    if dest.exists():
        log.info("Signed PDF already saved as %s.", dest.name)
        return
    url = packet.get("signed_document_url") or data.get("signed_document_url")
    source = "the webhook"
    if not url:
        # The link can be missing from the webhook, so read the packet once.
        url = dr.get_packet(packet_id).get("signed_document_url")
        source = "GET /api/packets/:id"
    if not url:
        raise dr.DocRunnerError("DocRunner has no signed PDF link for this packet yet.")
    dr.download_signed_pdf(url, dest)
    log.info("Saved signed PDF to %s (link from %s).", dest, source)


class WebhookHandler(BaseHTTPRequestHandler):
    server_version = "docrunner-webhooks"

    def do_POST(self):
        if urlparse(self.path).path != WEBHOOK_PATH:
            return self._reply(404)

        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return self._reply(400)
        if length > MAX_BODY_BYTES:
            return self._reply(413)
        body = self.rfile.read(length)

        if not valid_signature(body, self.headers.get("X-DocRunner-Signature")):
            log.warning("Rejected a delivery with a missing or wrong signature.")
            return self._reply(401)

        try:
            payload = json.loads(body)
        except ValueError:
            return self._reply(400)
        if not isinstance(payload, dict):
            return self._reply(400)

        event = str(payload.get("event") or "")
        delivery_id = str(payload.get("delivery_id") or "")
        account_id = payload.get("account_id")
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        packet = data.get("packet") if isinstance(data.get("packet"), dict) else {}
        packet_id = packet.get("id")

        pinned_account = os.environ.get("DOCRUNNER_ACCOUNT_ID", "").strip()
        if pinned_account and str(account_id) != pinned_account:
            log.warning("Ignored %s from account %s (expected %s).", event, account_id, pinned_account)
            return self._reply(200)

        log.info(
            "event=%s delivery=%s packet=%s status=%s account=%s",
            event, delivery_id, packet_id, packet.get("status"), account_id,
        )
        if delivery_id and is_seen(delivery_id):
            log.info("Delivery %s was already handled. Skipped.", delivery_id)
            return self._reply(200)

        if event == "Packet.Completed":
            if packet_id is None:
                log.error("Packet.Completed had no packet id. Nothing to save.")
                return self._reply(200)
            try:
                save_signed_pdf(payload)
            except (dr.DocRunnerError, OSError, ValueError) as err:
                # A 500 makes DocRunner retry this delivery later.
                log.error("Could not save the signed PDF for packet %s: %s", packet_id, err)
                return self._reply(500)

        remember(delivery_id)
        return self._reply(200)

    def _reply(self, status):
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format, *args):
        """Silence the default access log. The events are logged above."""


def setup_logging():
    LOG_DIR.mkdir(exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for handler in (logging.FileHandler(LOG_DIR / "webhook_events.log"), logging.StreamHandler()):
        handler.setFormatter(formatter)
        log.addHandler(handler)
    log.setLevel(logging.INFO)


def main():
    dr.load_env()
    if not os.environ.get("DOCRUNNER_WEBHOOK_SECRET", "").strip():
        raise SystemExit("Set DOCRUNNER_WEBHOOK_SECRET in .env first.")
    setup_logging()
    port = int(os.environ.get("WEBHOOK_PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), WebhookHandler)
    log.info("Listening on port %d at %s", port, WEBHOOK_PATH)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Stopped.")


if __name__ == "__main__":
    main()
