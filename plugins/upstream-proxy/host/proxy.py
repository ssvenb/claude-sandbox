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
}
STRIP_RESPONSE_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer",
    "transfer-encoding", "upgrade", "content-encoding", "content-length",
}


def log(msg: str) -> None:
    print(f"[upstream-proxy] {msg}", file=sys.stderr, flush=True)


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

    def permits(self, method: str, path: str) -> bool:
        return method.upper() in self.methods and path.startswith(self.paths)


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
            self.send_response(status)
            for key, value in headers:
                if key.lower() not in STRIP_RESPONSE_HEADERS:
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
        log(f"{route.name} → {route.upstream} ({'/'.join(sorted(route.methods))} {' '.join(route.paths)})")

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
