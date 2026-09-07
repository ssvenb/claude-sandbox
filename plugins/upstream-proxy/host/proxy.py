#!/usr/bin/env python3
"""Credential-injecting reverse proxies, one per route, each on its own unix socket.

Runs on the HOST, where the long-lived secrets live. The container gets only the sockets, so the
agent can *use* an upstream API without ever holding the key that authenticates to it.

Usage: proxy.py [--env-file FILE]... <routes.json> <socket-dir>

--env-file loads KEY=VALUE pairs into THIS process only. The secrets a route names are usually
kept in the target repo's own .env, which run.sh never sources; loading them here rather than in
host.sh keeps them out of run.sh's environment, where a later plugin's pass_env could otherwise
forward them into the container. Values already set in the environment win over the file.

Each route in routes.json:
  name           socket basename (<socket-dir>/<name>.sock)
  upstream       scheme://host[:port] every request is forwarded to
  allowMethods   HTTP methods the proxy will relay (default: GET)
  allowPaths     path prefixes the proxy will relay (default: everything)
  auth           how the credential is injected, see _Injector below
  maxBodyBytes   request body cap (default 8 MiB)
  port           loopback port the container reaches this route on, used to derive localUrl
  localUrl       what the sandbox calls this upstream (default http://127.0.0.1:<port>)
  rewriteUrls    rewrite localUrl <-> upstream in bodies and headers (default true)

The rewrite is what keeps the real endpoint, not just the credential, on the host: the container's
config holds only the dummy localUrl, requests that quote it are rewritten to the real upstream on
the way out, and anything the upstream says about itself is rewritten back on the way in. The
agent therefore never sees the upstream's hostname.

Anything not matching the method/path allowlists is refused with 403 without touching the
upstream, so the proxy is also a capability boundary, not only a secrecy one.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import socketserver
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


def load_env_file(path: str) -> int:
    """Merge KEY=VALUE lines from a .env-style file into os.environ. Returns how many were set.

    Deliberately conservative: no ${VAR} interpolation and no command substitution, so a value is
    always exactly the bytes in the file. Anything already in the environment is left alone, which
    lets the caller override a file value without editing the file.
    """
    count = 0
    with open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            key, sep, value = line.partition("=")
            key = key.strip()
            if not sep or not key.isidentifier():
                log(f"{path}:{lineno}: ignoring unparsable line")
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                # Quoted: let shlex handle escapes rather than blindly trimming the quotes.
                value = next(iter(shlex.split(value)), "")
            if key not in os.environ:
                os.environ[key] = value
                count += 1
    return count


class _Injector:
    """Turns a route's `auth` block into the headers that authenticate to the upstream."""

    def __init__(self, spec: dict):
        self.kind = spec.get("type", "none")
        self.spec = spec
        self._lock = threading.Lock()
        self._token = None
        self._expires = 0.0

    def _env(self, key: str) -> str:
        name = self.spec.get(key)
        if not name:
            raise ValueError(f"auth.{key} is required for type '{self.kind}'")
        value = os.environ.get(name)
        if not value:
            raise ValueError(f"${name} is unset on the host")
        return value

    def headers(self) -> dict:
        if self.kind == "none":
            return {}
        if self.kind == "header":
            return {self.spec.get("header", "Authorization"): self._env("valueEnv")}
        if self.kind == "bearer":
            return {"Authorization": f"Bearer {self._env('valueEnv')}"}
        if self.kind == "oauth2_client_credentials":
            return {"Authorization": f"Bearer {self._oauth_token()}"}
        raise ValueError(f"unknown auth.type '{self.kind}'")

    def _oauth_token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._expires:
                return self._token
            payload = {
                "grant_type": "client_credentials",
                "client_id": self._env("clientIdEnv"),
                "client_secret": self._env("clientSecretEnv"),
            }
            if self.spec.get("audience"):
                payload["audience"] = self.spec["audience"]
            req = urllib.request.Request(
                self.spec["tokenUrl"],
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


class _Route:
    def __init__(self, cfg: dict):
        self.name = cfg["name"]
        # ${VAR} in the upstream is expanded from the host env, so routes.json can reuse the
        # same CRIBL_SERVER_URL / AZURE_OPENAI_ENDPOINT the host tooling already sets.
        self.upstream = os.path.expandvars(cfg["upstream"]).rstrip("/")
        if not self.upstream.startswith(("http://", "https://")):
            raise ValueError(f"route '{self.name}': upstream must be an absolute http(s) URL")
        self.methods = {m.upper() for m in cfg.get("allowMethods", ["GET"])}
        self.paths = tuple(cfg.get("allowPaths", ["/"]))
        self.max_body = int(cfg.get("maxBodyBytes", DEFAULT_MAX_BODY))
        self.injector = _Injector(cfg.get("auth", {}))

        # The address the sandbox knows this upstream by. It is a dummy — a loopback port on the
        # container's socat forwarder — so that the real hostname can stay out of the repo's
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
        return method.upper() in self.methods and path.startswith(self.paths)

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
            if body and _rewritable(headers.get("Content-Type", "")):
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

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _relay

    return Handler


class _UnixServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    # BaseHTTPRequestHandler expects a (host, port) client address; AF_UNIX gives it "".
    def get_request(self):
        request, _ = super().get_request()
        return request, ("local", 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", action="append", default=[], metavar="FILE",
                        help="load secrets from a .env-style file into this process only")
    parser.add_argument("routes_file")
    parser.add_argument("sock_dir")
    args = parser.parse_args()
    routes_file, sock_dir = args.routes_file, args.sock_dir

    # Before the routes: their ${VAR} upstreams and *Env credential lookups both read os.environ.
    for env_file in args.env_file:
        log(f"loaded {load_env_file(env_file)} variable(s) from {env_file}")

    with open(routes_file, encoding="utf-8") as fh:
        raw = json.load(fh)

    servers = []
    for cfg in raw:
        route = _Route(cfg)
        path = os.path.join(sock_dir, f"{route.name}.sock")
        # AF_UNIX paths are capped around 108 bytes and the kernel's error says nothing useful.
        if len(path.encode()) > 100:
            log(f"socket path too long ({len(path)} bytes): {path}")
            return 1
        if os.path.exists(path):
            os.unlink(path)
        server = _UnixServer(path, _handler_for(route))
        # The container's root-init connects as root; node reaches it only through socat.
        os.chmod(path, 0o666)
        servers.append(server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        rewrite = f", rewriting {route.local_url} ↔ upstream" if route.rewrites else ""
        log(f"{route.name} → {route.upstream} "
            f"({'/'.join(sorted(route.methods))} {' '.join(route.paths)}{rewrite})")

    # Parent (run.sh) kills us on exit; until then just park.
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    for server in servers:
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
