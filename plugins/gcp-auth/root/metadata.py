#!/usr/bin/env python3
"""A stand-in for the GCE metadata server, so Google's client libraries authenticate on their own.

Usage: metadata.py --token-file FILE --account EMAIL --project ID --log FILE

Binds a free loopback port, prints it, and detaches. Every Google client library — and gcloud's
own GCE detection — honours GCE_METADATA_HOST / GCE_METADATA_IP / GCE_METADATA_ROOT, which
root-init.sh points here; the library then asks for a token exactly as it would on a GCE VM.
Tokens come from the file the host's credential refresher replaces (/run/credentials/gcp-token),
minted with a 1h lifetime, so the expiry reported is one hour after the file was written.

Under host-network the port is the host's, in reach of every other sandbox and of the host
itself, so only this container's own processes are answered (peer_owner). Runs as root so the
agent cannot replace it with a server of its own.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, "/usr/local/lib/sandbox")
from peer_owner import LOOPBACK, from_this_sandbox  # noqa: E402  (installed by the Dockerfile)

LIFETIME = 3600
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def handler_for(token_file: str, account: str, project: str):
    def token() -> dict:
        with open(token_file) as f:
            value = f.read().strip()
        left = int(os.stat(token_file).st_mtime + LIFETIME - time.time())
        return {"access_token": value, "expires_in": max(left, 0), "token_type": "Bearer"}

    def account_info() -> dict:
        return {"aliases": ["default"], "email": account, "scopes": SCOPES}

    # Paths under /computeMetadata/v1/, for "default" and the account's own email alike.
    def route(path: str, recursive: bool):
        if path in ("", "/"):
            return {"instance/": None, "project/": None} if recursive else "instance/\nproject/\n"
        if path == "project/project-id":
            return project
        if path == "universe/universe-domain":
            return "googleapis.com"
        if path == "instance/service-accounts/":
            if recursive:
                return {"default": account_info(), account: account_info()}
            return f"default/\n{account}/\n"
        for alias in ("default", account):
            base = f"instance/service-accounts/{alias}/"
            if path == base:
                return account_info() if recursive else "aliases\nemail\nscopes\ntoken\n"
            if path == base + "email":
                return account
            if path == base + "aliases":
                return "default"
            if path == base + "scopes":
                return "\n".join(SCOPES) + "\n"
            if path == base + "token":
                return token()
        return None

    class Handler(BaseHTTPRequestHandler):
        server_version = "Metadata Server for VM"
        sys_version = ""

        def log_message(self, fmt, *args):  # noqa: A002 - BaseHTTPRequestHandler API
            log(fmt % args)

        def _send(self, code: int, body, content_type: str = "application/text") -> None:
            if not isinstance(body, str):
                body, content_type = json.dumps(body), "application/json"
            data = body.encode()
            self.send_response(code)
            self.send_header("Metadata-Flavor", "Google")
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def do_GET(self):
            path, _, query = self.path.partition("?")
            # The real server refuses requests without the header, which is what keeps a browser or
            # an SSRF'd fetch from reading tokens; so does this one.
            if self.headers.get("Metadata-Flavor") != "Google":
                self._send(403, "Missing Metadata-Flavor:Google header.\n")
                return
            if path in ("", "/"):
                # The libraries' "am I on GCE?" ping only looks at the response header.
                self._send(200, "computeMetadata/\n")
                return
            prefix = "/computeMetadata/v1/"
            if not path.startswith(prefix):
                self._send(404, "Not found.\n")
                return
            try:
                body = route(path[len(prefix):], "recursive=true" in query)
            except OSError as e:
                log(f"cannot read {token_file}: {e}")
                self._send(503, "Token unavailable.\n")
                return
            self._send(200, body) if body is not None else self._send(404, "Not found.\n")

        do_HEAD = do_GET

    return Handler


class Server(HTTPServer):
    # Single-threaded on purpose: from_this_sandbox switches the process-wide euid.
    def verify_request(self, request, client_address) -> bool:
        if from_this_sandbox(client_address[1], self.server_address[1]):
            return True
        log(f"refused 127.0.0.1:{client_address[1]}: not a process of this sandbox")
        return False

    def get_request(self):
        request, addr = super().get_request()
        # A client that connects and stalls must not hold up everyone else's token requests.
        request.settimeout(5)
        return request, addr


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--token-file", required=True)
    ap.add_argument("--account", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--log", required=True)
    args = ap.parse_args()

    server = Server((LOOPBACK, 0), handler_for(args.token_file, args.account, args.project))
    print(server.server_address[1], flush=True)

    if os.fork():
        return 0
    os.setsid()
    out = os.open(args.log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    os.dup2(out, 1)
    os.dup2(out, 2)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
