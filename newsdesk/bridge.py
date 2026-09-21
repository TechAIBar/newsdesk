"""Run on the OpenClaw host. Exposes only bounded news summarization, never its Gateway token."""
from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import threading
import time

from .ai import authorize, resolve_command, summarize
from .config import Config
from .feeds import Item
from .lan import pairing_code


def ensure_certificate(directory: Path) -> tuple[Path, Path, str]:
    certificate, key = directory / "certificate.pem", directory / "private-key.pem"
    if not certificate.exists() or not key.exists():
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "NewsDesk LAN Summaries")])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(private.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
                .not_valid_after(now + timedelta(days=3650)).sign(private, hashes.SHA256()))
        key.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                             serialization.NoEncryption()))
        os.chmod(key, 0o600)
        certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    der = ssl.PEM_cert_to_DER_cert(certificate.read_text(encoding="ascii"))
    return certificate, key, hashlib.sha256(der).hexdigest()


class BridgeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, token, summarize_fn, max_per_hour=60):
        super().__init__(address, Handler)
        self.token = token
        self.summarize_fn = summarize_fn
        self.gate = threading.BoundedSemaphore(1)
        self.calls = deque()
        self.max_per_hour = max_per_hour


class Handler(BaseHTTPRequestHandler):
    server_version = "NewsDeskLAN/1"

    def setup(self):
        self.request.settimeout(120)
        super().setup()

    def log_message(self, format, *args):
        # Never print Authorization or arbitrary paths/queries.
        pass

    def respond(self, code, value):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def authenticated(self):
        actual = self.headers.get("Authorization", "")
        if not hmac.compare_digest(actual.encode(), ("Bearer " + self.server.token).encode()):
            self.respond(401, {"error": "unauthorized"})
            return False
        return True

    def do_GET(self):
        if self.authenticated():
            if self.path == "/health":
                self.respond(200, {"service": "newsdesk-openclaw", "scope": "summarize", "version": 1})
            else:
                self.respond(404, {"error": "not_found"})

    def do_POST(self):
        if not self.authenticated():
            return
        if self.path != "/summarize":
            self.respond(404, {"error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 64000 or self.headers.get("Transfer-Encoding"):
                self.respond(413, {"error": "body_limit"})
                return
            value = json.loads(self.rfile.read(length))
            rows = value["items"]
            if not isinstance(rows, list) or not 1 <= len(rows) <= 20:
                raise ValueError()
            items = []
            ids = set()
            for row in rows:
                if not isinstance(row, dict) or set(row) - {"id", "title", "abstract"}:
                    raise ValueError()
                ident, title, abstract = row["id"], row["title"], row.get("abstract", "")
                if not isinstance(ident, str) or not re.fullmatch(r"[a-f0-9]{24}", ident) or ident in ids:
                    raise ValueError()
                if not isinstance(title, str) or not 1 <= len(title) <= 220 or not isinstance(abstract, str) or len(abstract) > 600:
                    raise ValueError()
                ids.add(ident)
                items.append(Item(ident, "lan", "LAN", "news", title, "", summary=abstract))
        except (ValueError, KeyError, TypeError):
            self.respond(400, {"error": "invalid_news_items"})
            return
        if not self.server.gate.acquire(blocking=False):
            self.respond(429, {"error": "busy"})
            return
        try:
            now = time.monotonic()
            while self.server.calls and self.server.calls[0] < now - 3600:
                self.server.calls.popleft()
            if len(self.server.calls) >= self.server.max_per_hour:
                self.respond(429, {"error": "hourly_limit"})
                return
            self.server.calls.append(now)
            result = self.server.summarize_fn(items)
            self.respond(200, {"summaries": result})
        except Exception as exc:
            print(f"Summary failed ({type(exc).__name__}); check OpenClaw model credentials / doctor.", flush=True)
            self.respond(502, {"error": "openclaw_failed"})
        finally:
            self.server.gate.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description="OpenClaw host: authorize a LAN news-summary service")
    parser.add_argument("--advertise", required=True, help="This host's LAN IPv4 address, e.g. 192.168.1.20")
    parser.add_argument("--bind", default="", help="Defaults to the advertised LAN address")
    parser.add_argument("--port", type=int, default=18790)
    parser.add_argument("--command", default="openclaw", help="OpenClaw executable path on this host")
    parser.add_argument("--wsl", default="")
    parser.add_argument("--state-dir", type=Path, default=Path.home() / ".newsdesk-bridge")
    parser.add_argument("--rotate-token", action="store_true", help="Revoke previous pairing codes")
    parser.add_argument("--max-per-hour", type=int, default=60)
    args = parser.parse_args(argv)
    address = ipaddress.ip_address(args.advertise)
    if address.version != 4 or not address.is_private or address.is_unspecified:
        parser.error("--advertise must be this host's LAN IPv4 address")
    if not 1024 <= args.port <= 65535 or not 1 <= args.max_per_hour <= 600:
        parser.error("port must be 1024–65535; max-per-hour must be 1–600")
    state = args.state_dir.resolve()
    state.mkdir(parents=True, exist_ok=True)
    os.chmod(state, 0o700)
    # Keep the bridge's own consent/config separate from any desktop installation.
    os.environ["NEWSDESK_DATA_DIR"] = str(state)
    cfg = Config.load(state / "config.json")
    command = resolve_command(args.command, args.wsl)
    print("Testing the existing main agent through the Gateway...", flush=True)
    authorize(cfg, command)
    cfg.ai_limit = 20
    certificate, key, fingerprint = ensure_certificate(state)
    token_file = state / "access-token.txt"
    if args.rotate_token or not token_file.exists():
        token_file.write_text(secrets.token_urlsafe(32), encoding="ascii")
        os.chmod(token_file, 0o600)
    token = token_file.read_text(encoding="ascii").strip()
    server = BridgeServer((args.bind or str(address), args.port), token, lambda items: summarize(cfg, items), args.max_per_hour)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(certificate, key)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    url = f"https://{args.advertise}:{args.port}"
    print(f"\nNewsDesk summary service is listening at {url}", flush=True)
    print("Paste this pairing code into NewsDesk Settings > OpenClaw (keep it private):\n", flush=True)
    print(pairing_code(url, token, fingerprint), flush=True)
    print("\nScope: summarize only. Keep this process running. Ctrl+C stops access.", flush=True)
    print("To revoke all previous codes, restart with --rotate-token. Allow this TCP port only from your LAN.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
