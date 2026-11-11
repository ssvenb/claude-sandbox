"""plugins/upstream-proxy/host/proxy.py: the credential-injecting reverse proxy on the host."""
import http.client
import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from conftest import REPO, load

PROXY = REPO / "plugins/upstream-proxy/host/proxy.py"
proxy = load("plugins/upstream-proxy/host/proxy.py")


# --- units ---------------------------------------------------------------------------------

def test_load_env_file(tmp_path, monkeypatch):
    env = {"PRESET": "from-shell"}
    monkeypatch.setattr(proxy.os, "environ", env)
    path = tmp_path / ".env"
    path.write_text("\n".join([
        "# comment", "", "export A=1", 'B="two words"', "C='single'", "D = spaced ",
        'E="esc \\"q\\""', "PRESET=from-file", "not a line", "1BAD=x", "F=x=y",
    ]))
    assert proxy.load_env_file(str(path)) == 6
    assert env == {"PRESET": "from-shell", "A": "1", "B": "two words", "C": "single",
                   "D": "spaced", "E": 'esc "q"', "F": "x=y"}


@pytest.mark.parametrize("ctype, rewritable", [
    ("application/json", True), ("application/json; charset=utf-8", True),
    ("application/problem+json", True), ("text/html", True), ("application/atom+xml", True),
    ("application/x-www-form-urlencoded", True), ("Application/JSON", True),
    ("application/octet-stream", False), ("image/png", False), ("", False),
])
def test_rewritable_content_types(ctype, rewritable):
    assert proxy._rewritable(ctype) is rewritable


@pytest.mark.parametrize("spec, env, headers", [
    ({}, {}, {}),
    ({"type": "none"}, {}, {}),
    ({"type": "header", "header": "api-key", "valueEnv": "K"}, {"K": "s3"}, {"api-key": "s3"}),
    ({"type": "header", "valueEnv": "K"}, {"K": "s3"}, {"Authorization": "s3"}),
    ({"type": "bearer", "valueEnv": "K"}, {"K": "s3"}, {"Authorization": "Bearer s3"}),
])
def test_injector_headers(monkeypatch, spec, env, headers):
    monkeypatch.setattr(proxy.os, "environ", env)
    assert proxy._Injector(spec).headers() == headers


@pytest.mark.parametrize("spec, message", [
    ({"type": "bearer"}, "auth.valueEnv is required"),
    ({"type": "bearer", "valueEnv": "UNSET"}, "$UNSET is unset on the host"),
    ({"type": "magic"}, "unknown auth.type"),
])
def test_injector_errors(monkeypatch, spec, message):
    monkeypatch.setattr(proxy.os, "environ", {})
    with pytest.raises(ValueError, match=message.replace("$", r"\$")):
        proxy._Injector(spec).headers()


def fake_urlopen(monkeypatch, body):
    calls = []

    def urlopen(req, *a, **k):
        calls.append(req)
        return io.BytesIO(json.dumps(body).encode())
    monkeypatch.setattr(proxy.urllib.request, "urlopen", urlopen)
    return calls


def test_oauth2_token_is_fetched_once_and_cached(monkeypatch):
    monkeypatch.setattr(proxy.os, "environ", {"ID": "cid", "SECRET": "csec"})
    calls = fake_urlopen(monkeypatch, {"access_token": "minted", "expires_in": 3600})
    inj = proxy._Injector({"type": "oauth2_client_credentials", "tokenUrl": "https://idp/token",
                           "audience": "https://api", "clientIdEnv": "ID", "clientSecretEnv": "SECRET"})
    assert inj.headers() == {"Authorization": "Bearer minted"}
    assert inj.headers() == {"Authorization": "Bearer minted"}
    [req] = calls
    assert (req.full_url, req.get_method()) == ("https://idp/token", "POST")
    assert json.loads(req.data) == {"grant_type": "client_credentials", "client_id": "cid",
                                    "client_secret": "csec", "audience": "https://api"}


def test_oauth2_token_renews_a_minute_before_expiry(monkeypatch):
    monkeypatch.setattr(proxy.os, "environ", {"ID": "i", "SECRET": "s"})
    fake_urlopen(monkeypatch, {"access_token": "t", "expires_in": 600})
    inj = proxy._Injector({"type": "oauth2_client_credentials", "tokenUrl": "https://idp/token",
                           "clientIdEnv": "ID", "clientSecretEnv": "SECRET"})
    inj.headers()
    assert 535 < inj._expires - time.time() <= 540


@pytest.fixture
def gcloud(tmp_path, monkeypatch):
    log = tmp_path / "gcloud.args"
    path = tmp_path / "gcloud"
    path.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\necho host-token\n')
    path.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    return log


def test_gcp_token_impersonates_the_service_account(gcloud, monkeypatch):
    monkeypatch.setenv("SA_NAME", "reader")
    inj = proxy._Injector({"type": "gcp", "serviceAccount": "${SA_NAME}@p.iam.gserviceaccount.com"})
    assert inj.headers() == {"Authorization": "Bearer host-token"}
    assert inj.headers() == {"Authorization": "Bearer host-token"}
    assert gcloud.read_text() == ("auth print-access-token --quiet "
                                  "--impersonate-service-account=reader@p.iam.gserviceaccount.com\n")


def test_gcp_access_boundary_downscopes_through_sts(gcloud, monkeypatch):
    calls = fake_urlopen(monkeypatch, {"access_token": "downscoped", "expires_in": 1800})
    boundary = {"accessBoundaryRules": [{"availableResource": "//storage.googleapis.com/projects/_/buckets/b"}]}
    inj = proxy._Injector({"type": "gcp", "accessBoundary": boundary})
    assert inj.headers() == {"Authorization": "Bearer downscoped"}
    [req] = calls
    assert req.full_url == "https://sts.googleapis.com/v1/token"
    form = dict(urllib.parse.parse_qsl(req.data.decode()))
    assert form["subject_token"] == "host-token"
    assert json.loads(form["options"]) == {"accessBoundary": boundary}
    assert 1195 < inj._expires - time.time() <= 1200


def test_gcp_route_fails_at_startup_without_a_host_login(tmp_path, monkeypatch):
    (tmp_path / "gcloud").write_text("#!/bin/sh\necho 'please log in' >&2\nexit 1\n")
    (tmp_path / "gcloud").chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    with pytest.raises(RuntimeError, match="please log in"):
        proxy._Route({"name": "gcs", "upstream": "https://storage.googleapis.com", "auth": {"type": "gcp"}})


def route(**cfg):
    return proxy._Route({"name": "r", "upstream": "https://api.example.com", **cfg})


@pytest.mark.parametrize("cfg, message", [
    ({"upstream": "api.example.com"}, "absolute http"),
    ({"allowMethods": []}, "allowMethods is empty"),
    ({"allowPaths": []}, "allowPaths is empty"),
])
def test_route_validation(cfg, message):
    with pytest.raises(ValueError, match=message):
        route(**cfg)


def test_route_upstream_expands_host_variables(monkeypatch):
    monkeypatch.setenv("API_URL", "https://real.example.com/")
    assert route(upstream="${API_URL}").upstream == "https://real.example.com"


def test_route_allowlists():
    r = route(allowMethods=["get", "POST"], allowPaths=["/v1/", "/health"])
    assert r.permits("GET", "/v1/items") and r.permits("post", "/health")
    assert not r.permits("DELETE", "/v1/items")
    assert not r.permits("GET", "/v2/items")
    assert route().permits("PURGE", "/anything")


def test_route_rewrites_local_url_both_ways():
    r = route(port=8081)
    assert r.local_url == "http://127.0.0.1:8081" and r.rewrites
    out = r.to_upstream(b'{"cb": "http://127.0.0.1:8081/hook", "host": "127.0.0.1:8081"}')
    assert out == b'{"cb": "https://api.example.com/hook", "host": "api.example.com"}'
    assert r.to_local(out) == b'{"cb": "http://127.0.0.1:8081/hook", "host": "127.0.0.1:8081"}'


@pytest.mark.parametrize("cfg, local_url, rewrites", [
    ({"localUrl": "http://api.sandbox/"}, "http://api.sandbox", True),
    ({"port": 8081, "rewriteUrls": False}, "http://127.0.0.1:8081", False),
    ({}, "", False),
])
def test_route_local_url_options(cfg, local_url, rewrites):
    r = route(**cfg)
    assert (r.local_url, r.rewrites) == (local_url, rewrites)


# --- the running proxy ---------------------------------------------------------------------

class Upstream(ThreadingHTTPServer):
    """Records each request; answers by path."""
    daemon_threads = True

    def __init__(self):
        self.seen = []
        self.token_requests = 0
        super().__init__(("127.0.0.1", 0), self.Handler)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_address[1]}"

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _any(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            up = self.server
            if self.path == "/token":
                up.token_requests += 1
                return self._send(200, {"access_token": f"oauth-{up.token_requests}", "expires_in": 3600})
            up.seen.append({"method": self.command, "path": self.path, "headers": dict(self.headers),
                            "body": body})
            if self.path.startswith("/missing"):
                return self._send(404, {"error": "nope"})
            if self.path.startswith("/binary"):
                return self._send(200, up.url.encode(), "application/octet-stream")
            self._send(200, {"self": f"{up.url}/echo"}, extra={"Location": f"{up.url}/next"})

        def _send(self, code, body, ctype="application/json", extra=None):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def __getattr__(self, name):
            if name.startswith("do_"):
                return self._any
            raise AttributeError(name)


@pytest.fixture
def upstream():
    up = Upstream()
    threading.Thread(target=up.serve_forever, daemon=True).start()
    yield up
    up.shutdown()


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost", timeout=10)
        self.unix_path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(10)
        self.sock.connect(str(self.unix_path))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Proxy:
    def __init__(self, dirpath, routes, env_file=None, attest_dir=None, env=None):
        self.dir = dirpath
        (dirpath / "routes.json").write_text(json.dumps(routes))
        args = [sys.executable, PROXY]
        if env_file:
            args += ["--env-file", env_file]
        if attest_dir:
            args += ["--attest-dir", attest_dir]
        args += [dirpath / "routes.json", dirpath]
        self.proc = subprocess.Popen(args, env={"PATH": os.environ["PATH"], **(env or {})},
                                     stderr=subprocess.PIPE, text=True)
        names = [r["name"] for r in routes]
        deadline = time.time() + 10
        while not all((dirpath / f"{n}.sock").exists() for n in names):
            if self.proc.poll() is not None:
                raise AssertionError(f"proxy exited: {self.proc.stderr.read()}")
            assert time.time() < deadline, "proxy sockets never appeared"
            time.sleep(0.05)

    def request(self, method, path, name="api", body=None, headers=None):
        conn = UnixHTTPConnection(self.dir / f"{name}.sock")
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp, data

    def stop(self):
        self.proc.kill()
        self.proc.wait()
        return self.proc.stderr.read()


@pytest.fixture
def start(short_tmp):
    started = []

    def make(routes, **kw):
        p = Proxy(short_tmp, routes, **kw)
        started.append(p)
        return p
    yield make
    for p in started:
        p.stop()


def api_route(upstream, **cfg):
    return {"name": "api", "upstream": upstream.url, "port": 18080,
            "auth": {"type": "bearer", "valueEnv": "API_KEY"}, **cfg}


def test_credentials_are_injected_and_the_clients_are_dropped(start, upstream, short_tmp):
    (short_tmp / "secrets.env").write_text("API_KEY=from-the-env-file\n")
    p = start([api_route(upstream)], env_file=short_tmp / "secrets.env")
    resp, _ = p.request("GET", "/echo?q=1", headers={"Authorization": "Bearer placeholder",
                                                      "X-Api-Key": "placeholder", "X-Trace": "kept"})
    assert resp.status == 200
    [seen] = upstream.seen
    assert seen["path"] == "/echo?q=1"
    assert seen["headers"]["Authorization"] == "Bearer from-the-env-file"
    assert "X-Api-Key" not in seen["headers"]
    assert seen["headers"]["X-Trace"] == "kept"
    assert seen["headers"]["Host"] == upstream.url.removeprefix("http://")


def test_the_host_environment_wins_over_the_env_file(start, upstream, short_tmp):
    (short_tmp / "secrets.env").write_text("API_KEY=from-file\n")
    p = start([api_route(upstream)], env_file=short_tmp / "secrets.env", env={"API_KEY": "from-env"})
    p.request("GET", "/echo")
    assert upstream.seen[0]["headers"]["Authorization"] == "Bearer from-env"


def test_urls_are_rewritten_both_ways(start, upstream):
    p = start([api_route(upstream)], env={"API_KEY": "k"})
    body = json.dumps({"callback": "http://127.0.0.1:18080/hook"})
    resp, data = p.request("POST", "/echo", body=body, headers={
        "Content-Type": "application/json", "Referer": "http://127.0.0.1:18080/page"})
    seen = upstream.seen[0]
    assert json.loads(seen["body"]) == {"callback": f"{upstream.url}/hook"}
    assert seen["headers"]["Referer"] == f"{upstream.url}/page"
    assert json.loads(data) == {"self": "http://127.0.0.1:18080/echo"}
    assert resp.getheader("Location") == "http://127.0.0.1:18080/next"
    assert int(resp.getheader("Content-Length")) == len(data)


def test_binary_bodies_pass_byte_for_byte(start, upstream):
    p = start([api_route(upstream)], env={"API_KEY": "k"})
    payload = b"http://127.0.0.1:18080"
    _, data = p.request("PUT", "/binary", body=payload, headers={"Content-Type": "application/octet-stream"})
    assert upstream.seen[0]["body"] == payload
    assert data == upstream.url.encode()


def test_request_body_rewrite_ignores_header_case(start, upstream):
    """Node's fetch sends lowercase header names; the rewritten body must still arrive whole."""
    p = start([api_route(upstream, localUrl="http://api.local")], env={"API_KEY": "k"})
    body = '{"cb": "http://api.local/hook"}'
    p.request("POST", "/echo", body=body,
              headers={"content-type": "application/json", "content-length": str(len(body))})
    assert json.loads(upstream.seen[0]["body"]) == {"cb": f"{upstream.url}/hook"}


def test_allowlists_refuse_without_reaching_the_upstream(start, upstream):
    p = start([api_route(upstream, allowMethods=["GET"], allowPaths=["/echo"])], env={"API_KEY": "k"})
    assert p.request("GET", "/echo")[0].status == 200
    for method, path in (("DELETE", "/echo"), ("GET", "/admin")):
        resp, data = p.request(method, path)
        assert resp.status == 403
        assert "not permitted" in json.loads(data)["error"]
    assert len(upstream.seen) == 1


def test_any_method_is_relayed_without_an_allowlist(start, upstream):
    p = start([api_route(upstream)], env={"API_KEY": "k"})
    assert p.request("PURGE", "/echo")[0].status == 200
    assert upstream.seen[0]["method"] == "PURGE"


def test_oversized_bodies_are_refused(start, upstream):
    p = start([api_route(upstream, maxBodyBytes=10)], env={"API_KEY": "k"})
    assert p.request("POST", "/echo", body=b"x" * 11)[0].status == 413
    assert p.request("POST", "/echo", body=b"x" * 10)[0].status == 200


def test_upstream_errors_pass_through(start, upstream):
    p = start([api_route(upstream)], env={"API_KEY": "k"})
    resp, data = p.request("GET", "/missing")
    assert (resp.status, json.loads(data)) == (404, {"error": "nope"})


def test_unreachable_upstream_is_a_502(start):
    p = start([{"name": "api", "upstream": f"http://127.0.0.1:{free_port()}"}])
    resp, data = p.request("GET", "/")
    assert resp.status == 502 and "could not reach" in data.decode()


def test_missing_credential_is_a_502(start, upstream):
    p = start([api_route(upstream)])
    resp, data = p.request("GET", "/echo")
    assert resp.status == 502 and "credentials" in data.decode()
    assert upstream.seen == []


def test_oauth2_route_mints_once_for_many_requests(start, upstream):
    auth = {"type": "oauth2_client_credentials", "tokenUrl": f"{upstream.url}/token",
            "clientIdEnv": "CID", "clientSecretEnv": "CSECRET"}
    p = start([api_route(upstream, auth=auth)], env={"CID": "i", "CSECRET": "s"})
    p.request("GET", "/echo")
    p.request("GET", "/echo")
    assert [s["headers"]["Authorization"] for s in upstream.seen] == ["Bearer oauth-1"] * 2
    assert upstream.token_requests == 1


def test_each_route_gets_its_own_socket(start, upstream):
    p = start([api_route(upstream), {"name": "other", "upstream": upstream.url}], env={"API_KEY": "k"})
    p.request("GET", "/echo", name="other")
    assert "Authorization" not in upstream.seen[0]["headers"]
    assert oct((p.dir / "other.sock").stat().st_mode & 0o777) == "0o666"


@pytest.mark.parametrize("routes, message", [
    ([{"name": "api", "upstream": "http://x", "allowMethods": []}], "allowMethods is empty"),
    ([{"name": "x" * 120, "upstream": "http://x"}], "socket path too long"),
])
def test_bad_routes_fail_the_start(short_tmp, routes, message):
    (short_tmp / "routes.json").write_text(json.dumps(routes))
    done = subprocess.run([sys.executable, PROXY, short_tmp / "routes.json", short_tmp],
                          capture_output=True, text=True, timeout=10)
    assert done.returncode != 0 and message in done.stderr


# --- host-network: the proxy holds the ports, sandboxes attest for their own connections ----

class Attestor:
    def __init__(self, path, answer):
        self.answer = answer
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.bind(str(path))
        self.sock.listen()
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        while True:
            conn, _ = self.sock.accept()
            with conn:
                conn.makefile("rb").readline()
                conn.sendall(self.answer)


def tcp_get(port, path="/echo"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", path)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data


def test_attested_connections_on_the_port_are_relayed(start, upstream, short_tmp):
    (short_tmp / "attest").mkdir()
    port = free_port()
    attestor = Attestor(short_tmp / "attest/run1.sock", b"1\n")
    start([api_route(upstream, port=port)], attest_dir=short_tmp / "attest", env={"API_KEY": "k"})
    assert tcp_get(port)[0] == 200
    attestor.answer = b"0\n"
    status, data = tcp_get(port)
    assert status == 403 and b"another project" in data


def test_a_dead_attestors_socket_is_removed(start, upstream, short_tmp):
    (short_tmp / "attest").mkdir()
    dead = socket.socket(socket.AF_UNIX)
    dead.bind(str(short_tmp / "attest/gone.sock"))
    dead.close()  # the file stays, nothing listens: what a killed container leaves behind
    port = free_port()
    start([api_route(upstream, port=port)], attest_dir=short_tmp / "attest", env={"API_KEY": "k"})
    assert tcp_get(port)[0] == 403
    assert not (short_tmp / "attest/gone.sock").exists()


def test_attest_mode_needs_a_port_per_route(short_tmp):
    (short_tmp / "routes.json").write_text(json.dumps([{"name": "api", "upstream": "http://x"}]))
    done = subprocess.run([sys.executable, PROXY, "--attest-dir", short_tmp, short_tmp / "routes.json",
                           short_tmp], capture_output=True, text=True, timeout=10)
    assert done.returncode == 1 and "needs a port" in done.stderr
