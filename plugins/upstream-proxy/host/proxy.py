#!/usr/bin/env python3
"""Credential-injecting reverse proxies, one per route, each on its own unix socket.

Runs on the HOST, where the long-lived secrets live. The container gets only the sockets, so the
agent can *use* an upstream API without ever holding the key that authenticates to it.

Usage: proxy.py [--auth-file FILE] <routes.json> <socket-dir>

One proxy serves every sandbox of a project at once: run.sh starts it for the first and stops it
after the last, and it outlives the terminal of the run that started it.

--auth-file is your authentications (~/.config/claude-sandbox/auth.json), where a route's
`auth.credential` is looked up. It is read by THIS process alone, so a key never enters run.sh's
environment, where a later plugin's pass_env could forward it into the container; again on every
request (a new key takes effect at once); and refused unless only its owner can read it.

Each route in routes.json:
  name           socket basename (<socket-dir>/<name>.sock)
  upstream       scheme://host[:port] every request is forwarded to
  allowMethods   HTTP methods the proxy will relay (default: every method)
  allowPaths     path prefixes the proxy will relay (default: every path)
  auth           how the credential is injected, see _Injector below
  maxBodyBytes   request body cap (default 8 MiB)
  port           loopback port the container reaches this route on, used to derive localUrl
  localUrl       what the sandbox calls this upstream (default http://127.0.0.1:<port>)
  rewriteUrls    rewrite localUrl <-> upstream in bodies and headers (default true)

The rewrite keeps the real endpoint, not just the credential, on the host: the container knows only
the dummy localUrl, which is swapped for the upstream on the way out and swapped back on the way
in. Anything outside the method/path allowlists is refused with 403 without touching the upstream,
so the proxy is a capability boundary as well as a secrecy one.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import socketserver
import subprocess
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler

DEFAULT_MAX_BODY = 8 * 1024 * 1024
TIMEOUT = 120

# Hop-by-hop headers, plus the ones we own: the client's idea of Host and of authentication is
# never forwarded — that is the whole point.
STRIP_REQUEST_HEADERS = {
    "host", "authorization", "api-key", "x-api-key", "connection", "keep-alive",
    "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade",
    # Dropped so the upstream answers in plain text: we rewrite URLs in the response body, and a
    # compressed body would sail through unchanged (Content-Encoding is stripped on the way back).
    "accept-encoding",
}

# Only bodies we can safely search-and-replace as text get rewritten; images and octet-streams are
# forwarded byte for byte.
REWRITABLE_TYPES = ("application/json", "application/xml", "application/javascript",
                    "application/x-www-form-urlencoded", "text/", "+json", "+xml")
STRIP_RESPONSE_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer",
    "transfer-encoding", "upgrade", "content-encoding", "content-length",
}


def log(msg: str) -> None:
    print(f"[upstream-proxy] {msg}", file=sys.stderr, flush=True)


def _rewritable(content_type: str) -> bool:
    ct = content_type.split(";", 1)[0].strip().lower()
    return bool(ct) and any(marker in ct for marker in REWRITABLE_TYPES)


AUTH_FILE = None  # --auth-file


USABLE = ("api-key", "oauth2-client", "gcp-service-account")


def credential(name: str) -> dict:
    """The entry called `name` in AUTH_FILE, of a type a route can use."""
    if not AUTH_FILE:
        raise ValueError(f"auth.credential '{name}' needs the authentications file (--auth-file)")
    try:
        if os.stat(AUTH_FILE).st_mode & 0o077:
            raise ValueError(f"{AUTH_FILE} holds keys: make it readable by you alone (chmod 600 {AUTH_FILE})")
        with open(AUTH_FILE, encoding="utf-8") as fh:
            entries = json.load(fh)
    except (OSError, ValueError) as e:
        raise ValueError(f"auth.credential '{name}': {e}") from None
    entry = entries.get(name) if isinstance(entries, dict) else None
    if not isinstance(entry, dict):
        raise ValueError(f"auth.credential '{name}': {AUTH_FILE} has no authentication of that name")
    if entry.get("type") not in USABLE:
        raise ValueError(f"auth.credential '{name}' is a {entry.get('type')}; a route takes an {', '.join(USABLE)}")
    for key in {"api-key": ["key"], "oauth2-client": ["tokenUrl", "clientId", "clientSecret"]}.get(entry["type"], []):
        if not entry.get(key):
            raise ValueError(f"auth.credential '{name}' lacks {key}")
    return entry


class _Injector:
    """Turns a route's `auth` block into the headers that authenticate to the upstream: the type of
    the credential it names says how — an api-key as it is (in `header`, else as a bearer token),
    an oauth2-client's or a gcp-service-account's minted token as a bearer token."""

    def __init__(self, spec: dict):
        self.spec = spec
        self.name = spec.get("credential")
        self._lock = threading.Lock()
        self._token = None
        self._expires = 0.0

    def kind(self) -> str:
        return credential(self.name)["type"] if self.name else "none"

    def headers(self) -> dict:
        if not self.name:
            return {}
        entry = credential(self.name)
        if entry["type"] == "api-key":
            header = self.spec.get("header")
            return {header: str(entry["key"])} if header else {"Authorization": f"Bearer {entry['key']}"}
        if entry["type"] == "oauth2-client":
            return {"Authorization": f"Bearer {self._oauth_token(entry)}"}
        return {"Authorization": f"Bearer {self._gcp_token(entry)}"}

    def _oauth_token(self, entry: dict) -> str:
        with self._lock:
            if self._token and time.time() < self._expires:
                return self._token
            payload = {
                "grant_type": "client_credentials",
                "client_id": entry["clientId"],
                "client_secret": entry["clientSecret"],
            }
            if entry.get("audience"):
                payload["audience"] = entry["audience"]
            req = urllib.request.Request(
                entry["tokenUrl"],
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                body = json.load(resp)
            self._token = body["access_token"]
            # Renew a minute early so an in-flight request never rides an expiring token.
            self._expires = time.time() + max(int(body.get("expires_in", 3600)) - 60, 60)
            log(f"minted upstream token, valid ~{int(self._expires - time.time())}s")
            return self._token


    def _gcp_token(self, entry: dict) -> str:
        """A Google access token for the entry's `serviceAccount` (none: the host's own account),
        minted by the host's own gcloud login.

        The host identity needs roles/iam.serviceAccountTokenCreator on the service account, which
        in turn holds only the roles the sandbox should have (e.g. storage.objectViewer on one
        bucket). An optional `accessBoundary` (a Credential Access Boundary, Cloud Storage only)
        downscopes the token further via Google's STS, so even a broadly-granted account yields a
        token good for just the listed buckets/prefixes. Nothing here ever leaves the host.
        """
        with self._lock:
            if self._token and time.time() < self._expires:
                return self._token
            account = entry.get("serviceAccount", "")
            cmd = ["gcloud", "auth", "print-access-token", "--quiet"]
            if account:
                cmd.append(f"--impersonate-service-account={account}")
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
            if done.returncode != 0:
                raise RuntimeError(f"{' '.join(cmd)} failed: {done.stderr.strip()}")
            token = done.stdout.strip()
            # gcloud does not report the expiry; its tokens live an hour.
            lifetime = 3600
            boundary = self.spec.get("accessBoundary")
            if boundary:
                form = urllib.parse.urlencode({
                    "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                    "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
                    "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
                    "subject_token": token,
                    "options": json.dumps({"accessBoundary": boundary}),
                }).encode()
                req = urllib.request.Request(
                    "https://sts.googleapis.com/v1/token", data=form,
                    headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST",
                )
                with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                    body = json.load(resp)
                token = body["access_token"]
                lifetime = int(body.get("expires_in", lifetime))
            self._token = token
            # Renew well before gcloud's cached token underneath could lapse.
            self._expires = time.time() + max(lifetime - 600, 60)
            who = account or "the host's gcloud account"
            log(f"minted GCP token for {who}{' (downscoped)' if boundary else ''}")
            return self._token


class _Route:
    def __init__(self, cfg: dict):
        self.name = cfg["name"]
        # ${VAR} in the upstream is expanded from the host env, so routes.json can reuse the
        # same CRIBL_SERVER_URL / AZURE_OPENAI_ENDPOINT the host tooling already sets.
        self.upstream = os.path.expandvars(cfg["upstream"]).rstrip("/")
        if not self.upstream.startswith(("http://", "https://")):
            raise ValueError(f"route '{self.name}': upstream must be an absolute http(s) URL")
        # Unset means unrestricted. An empty list would refuse every request, which is never what
        # the author meant — most likely a list emptied while editing — so it fails the start.
        for key in ("allowMethods", "allowPaths"):
            if cfg.get(key) == []:
                raise ValueError(f"route '{self.name}': {key} is empty; omit it to allow everything")
        methods = cfg.get("allowMethods")
        self.methods = {m.upper() for m in methods} if methods else None
        self.paths = tuple(cfg.get("allowPaths") or ["/"])
        self.max_body = int(cfg.get("maxBodyBytes", DEFAULT_MAX_BODY))
        auth = cfg.get("auth") or {}
        # A route still in the old shape ({type, valueEnv, …}) would otherwise run with no
        # credential at all, and the upstream answers the agent's request with a bare 401.
        stale = sorted(set(auth) - {"credential", "header", "accessBoundary"})
        if stale:
            raise ValueError(f"route '{self.name}': auth.{', auth.'.join(stale)} is not read any more; "
                             "name an authentication in auth.credential instead")
        self.injector = _Injector(auth)
        # Fail at startup, not on the agent's first request: a bad login or a missing
        # tokenCreator grant should stop run.sh while the user is still watching.
        if self.injector.kind() == "gcp-service-account":
            self.injector.headers()

        # The address the sandbox knows this upstream by. It is a dummy — a loopback port on the
        # container's forwarder — so that the real hostname can stay out of the repo's
        # config and out of the container's environment entirely.
        port = cfg.get("port")
        self.local_url = str(cfg.get("localUrl") or (f"http://127.0.0.1:{port}" if port else "")).rstrip("/")
        self._out_pairs: list[tuple[bytes, bytes]] = []
        self._in_pairs: list[tuple[bytes, bytes]] = []
        if self.local_url and cfg.get("rewriteUrls", True):
            local_host = urllib.parse.urlsplit(self.local_url).netloc
            up_host = urllib.parse.urlsplit(self.upstream).netloc
            # Full URLs first: replacing the bare host inside a URL we already rewrote would be a
            # no-op, but doing it the other way round would leave a mangled scheme behind.
            self._out_pairs = [
                (self.local_url.encode(), self.upstream.encode()),
                (local_host.encode(), up_host.encode()),
            ]
            self._in_pairs = [(b, a) for a, b in self._out_pairs]

    @property
    def rewrites(self) -> bool:
        return bool(self._out_pairs)

    def permits(self, method: str, path: str) -> bool:
        return (self.methods is None or method.upper() in self.methods) and path.startswith(self.paths)

    def to_upstream(self, data: bytes) -> bytes:
        """Rewrite the sandbox's dummy address to the real one, on its way out."""
        for src, dst in self._out_pairs:
            data = data.replace(src, dst)
        return data

    def to_local(self, data: bytes) -> bytes:
        """Rewrite the real address back to the sandbox's dummy one, on its way in."""
        for src, dst in self._in_pairs:
            data = data.replace(src, dst)
        return data


def _handler_for(route: _Route):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "upstream-proxy"

        def log_message(self, fmt, *args):  # noqa: A002 - BaseHTTPRequestHandler API
            log(f"{route.name}: {fmt % args}")

        def _refuse(self, code: int, reason: str) -> None:
            body = json.dumps({"error": reason}).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _relay(self) -> None:
            path = urllib.parse.urlsplit(self.path).path
            if not route.permits(self.command, path):
                self.log_message("refused %s %s", self.command, path)
                self._refuse(403, f"{self.command} {path} is not permitted by the sandbox proxy")
                return

            length = int(self.headers.get("Content-Length") or 0)
            if length > route.max_body:
                self._refuse(413, "request body too large")
                return
            body = self.rfile.read(length) if length else None

            headers = {
                k: v for k, v in self.headers.items()
                if k.lower() not in STRIP_REQUEST_HEADERS
            }
            # The agent only ever knows the dummy localUrl, so anything it quotes back — a webhook
            # target, a Referer, an id in a JSON payload — has to be restored to the real endpoint.
            if body and _rewritable(self.headers.get("Content-Type", "")):  # any spelling
                body = route.to_upstream(body)
                headers["Content-Length"] = str(len(body))
            for key in list(headers):
                if key.lower() not in ("content-length", "content-type"):
                    headers[key] = route.to_upstream(headers[key].encode()).decode("latin-1")
            try:
                headers.update(route.injector.headers())
            except Exception as exc:  # credential problem is the host's fault, not the agent's
                self.log_message("credential error: %s", exc)
                self._refuse(502, "sandbox proxy could not obtain upstream credentials")
                return

            url = route.upstream + self.path
            req = urllib.request.Request(url, data=body, headers=headers, method=self.command)
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl.create_default_context()) as resp:
                    self._respond(resp.status, resp.headers.items(), resp.read())
            except urllib.error.HTTPError as exc:
                # Pass upstream errors through verbatim: the agent needs to see a real 404/429.
                self._respond(exc.code, exc.headers.items(), exc.read())
            except Exception as exc:
                self.log_message("upstream error: %s", exc)
                self._refuse(502, "sandbox proxy could not reach the upstream")

        def _respond(self, status: int, headers, body: bytes) -> None:
            kept = [(k, v) for k, v in headers if k.lower() not in STRIP_RESPONSE_HEADERS]
            content_type = next((v for k, v in kept if k.lower() == "content-type"), "")
            # Hide the upstream wherever it names itself: Location and Link redirects, and any
            # self-referential URL in the body.
            if _rewritable(content_type):
                body = route.to_local(body)
            self.send_response(status)
            for key, value in kept:
                if key.lower() != "content-type":
                    value = route.to_local(value.encode("latin-1")).decode("latin-1")
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def __getattr__(self, name):
            # http.server dispatches to do_<METHOD> and answers 501 where there is none; route every
            # method to _relay instead, so the route's allowlist is the only thing that decides.
            if name.startswith("do_"):
                return self._relay
            raise AttributeError(name)

    return Handler


class _UnixServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    # BaseHTTPRequestHandler expects a (host, port) client address; AF_UNIX gives it "".
    def get_request(self):
        request, _ = super().get_request()
        return request, ("local", 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auth-file", metavar="FILE",
                        help="your authentications, where a route's auth.credential is looked up")
    parser.add_argument("routes_file")
    parser.add_argument("sock_dir")
    args = parser.parse_args()
    routes_file, sock_dir = args.routes_file, args.sock_dir
    global AUTH_FILE
    AUTH_FILE = args.auth_file

    # Every sandbox of the project uses this one process, so it must not die with the terminal of
    # the run that happened to start it (a SIGHUP to that run's process group).
    with contextlib.suppress(OSError):
        os.setsid()

    with open(routes_file, encoding="utf-8") as fh:
        raw = json.load(fh)

    servers = []
    for cfg in raw:
        try:
            route = _Route(cfg)
        except (ValueError, RuntimeError) as e:  # a misconfigured route or no host login: what is wrong, not a traceback
            log(f"route '{cfg.get('name')}': {e}")
            return 1
        path = os.path.join(sock_dir, f"{route.name}.sock")
        # AF_UNIX paths are capped around 108 bytes and the kernel's error says nothing useful.
        if len(path.encode()) > 100:
            log(f"socket path too long ({len(path)} bytes): {path}")
            return 1
        handler = _handler_for(route)
        if os.path.exists(path):
            os.unlink(path)
        servers.append(_UnixServer(path, handler))
        # The container's root-init connects as root; node reaches it only through the forwarder.
        os.chmod(path, 0o666)
        rewrite = f", rewriting {route.local_url} ↔ upstream" if route.rewrites else ""
        log(f"{route.name} → {route.upstream} "
            f"({'/'.join(sorted(route.methods)) if route.methods else 'any method'} "
            f"{' '.join(route.paths)}{rewrite})")

    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()

    # The last run.sh of the project to exit kills us; until then just park.
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    for server in servers:
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
