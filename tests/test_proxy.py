"""plugins/upstream-proxy/host/proxy.py: the credential-injecting reverse proxy on the host."""
import datetime
import http.client
import io
import json
import os
import re
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

@pytest.mark.parametrize("ctype, rewritable", [
    ("application/json", True), ("application/json; charset=utf-8", True),
    ("application/problem+json", True), ("text/html", True), ("application/atom+xml", True),
    ("application/x-www-form-urlencoded", True), ("Application/JSON", True),
    ("application/octet-stream", False), ("image/png", False), ("", False),
])
def test_rewritable_content_types(ctype, rewritable):
    assert proxy._rewritable(ctype) is rewritable


@pytest.fixture
def auth(tmp_path, monkeypatch):
    """Writes the authentications file the proxy reads (--auth-file), readable by its owner alone."""
    file = tmp_path / "auth.json"

    def write(entries, mode=0o600):
        file.write_text(json.dumps(entries))
        file.chmod(mode)
    monkeypatch.setattr(proxy, "AUTH_FILE", str(file))
    write.file = file
    return write


@pytest.mark.parametrize("spec, headers", [
    ({}, {}),
    ({"header": "x-api-key"}, {}),  # no credential named: no authentication
    ({"credential": "openai"}, {"Authorization": "Bearer sk-1"}),
    ({"credential": "openai", "header": "x-api-key"}, {"x-api-key": "sk-1"}),
])
def test_an_api_key_is_sent_as_a_bearer_token_or_in_the_header_named(auth, spec, headers):
    auth({"openai": {"type": "api-key", "key": "sk-1"}})
    assert proxy._Injector(spec).headers() == headers


def test_a_credential_is_read_on_every_use_from_a_file_only_its_owner_can_read(auth, monkeypatch):
    auth({"openai": {"type": "api-key", "key": "sk-1"}, "coder": {"type": "github-app", "appId": "1"},
          "half": {"type": "oauth2-client", "tokenUrl": "https://idp/token", "clientId": "i"}})
    inj = proxy._Injector({"credential": "openai"})
    assert inj.headers() == {"Authorization": "Bearer sk-1"}
    auth({"openai": {"type": "api-key", "key": "sk-2"}, "coder": {"type": "github-app"},
          "half": {"type": "oauth2-client", "tokenUrl": "https://idp/token", "clientId": "i"}})
    assert inj.headers() == {"Authorization": "Bearer sk-2"}  # rotated: no restart
    for name, message in (("nobody", "has no authentication of that name"),
                          ("coder", "is a github-app; a route takes an api-key, oauth2-client, gcp-service-account"),
                          ("half", "lacks clientSecret")):
        with pytest.raises(ValueError, match=f"auth.credential '{name}'.*{re.escape(message)}"):
            proxy._Injector({"credential": name}).headers()
    auth({"openai": {"type": "api-key", "key": "sk-2"}}, 0o644)
    with pytest.raises(ValueError, match="readable by you alone"):
        inj.headers()
    monkeypatch.setattr(proxy, "AUTH_FILE", None)
    with pytest.raises(ValueError, match="needs the authentications file"):
        inj.headers()


def fake_urlopen(monkeypatch, body):
    calls = []

    def urlopen(req, *a, **k):
        calls.append(req)
        return io.BytesIO(json.dumps(body).encode())
    monkeypatch.setattr(proxy.urllib.request, "urlopen", urlopen)
    return calls


def test_oauth2_token_is_fetched_once_and_cached(auth, monkeypatch):
    auth({"idp": {"type": "oauth2-client", "tokenUrl": "https://idp/token", "audience": "https://api",
                  "clientId": "cid", "clientSecret": "csec"}})
    calls = fake_urlopen(monkeypatch, {"access_token": "minted", "expires_in": 3600})
    inj = proxy._Injector({"credential": "idp"})
    assert inj.headers() == {"Authorization": "Bearer minted"}
    assert inj.headers() == {"Authorization": "Bearer minted"}
    [req] = calls
    assert (req.full_url, req.get_method()) == ("https://idp/token", "POST")
    assert json.loads(req.data) == {"grant_type": "client_credentials", "client_id": "cid",
                                    "client_secret": "csec", "audience": "https://api"}


def test_oauth2_token_renews_a_minute_before_expiry(auth, monkeypatch):
    auth({"idp": {"type": "oauth2-client", "tokenUrl": "https://idp/token", "clientId": "i", "clientSecret": "s"}})
    fake_urlopen(monkeypatch, {"access_token": "t", "expires_in": 600})
    inj = proxy._Injector({"credential": "idp"})
    inj.headers()
    assert 535 < inj._expires - time.time() <= 540


class FakeCreds:
    """google-auth credentials: the host's login, or one impersonating target_principal."""
    def __init__(self, log, target_principal=None, **kw):
        self.log, self.who, self.token, self.expiry = log, target_principal, None, None

    def refresh(self, request):
        self.log.append(self.who)
        self.token = "host-token"
        self.expiry = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(hours=1)


@pytest.fixture
def gcloud(monkeypatch):
    """The host's application default credentials, faked; the accounts tokens were minted for."""
    log = []
    monkeypatch.setattr(proxy.google.auth, "default", lambda scopes: (FakeCreds(log), None))
    monkeypatch.setattr(proxy.impersonated_credentials, "Credentials",
                        lambda source_credentials, **kw: FakeCreds(log, **kw))
    return log


def test_gcp_token_impersonates_the_service_account(gcloud, auth):
    auth({"gcs": {"type": "gcp-service-account", "serviceAccount": "reader@p.iam.gserviceaccount.com"}})
    inj = proxy._Injector({"credential": "gcs"})
    assert inj.headers() == {"Authorization": "Bearer host-token"}
    assert inj.headers() == {"Authorization": "Bearer host-token"}
    assert gcloud == ["reader@p.iam.gserviceaccount.com"]  # minted once, for the service account


def test_gcp_access_boundary_downscopes_through_sts(gcloud, auth, monkeypatch):
    auth({"me": {"type": "gcp-service-account"}})  # no serviceAccount: the host's own account
    calls = fake_urlopen(monkeypatch, {"access_token": "downscoped", "expires_in": 1800})
    boundary = {"accessBoundaryRules": [{"availableResource": "//storage.googleapis.com/projects/_/buckets/b"}]}
    inj = proxy._Injector({"credential": "me", "accessBoundary": boundary})
    assert inj.headers() == {"Authorization": "Bearer downscoped"}
    [req] = calls
    assert req.full_url == "https://sts.googleapis.com/v1/token"
    form = dict(urllib.parse.parse_qsl(req.data.decode()))
    assert form["subject_token"] == "host-token"
    assert json.loads(form["options"]) == {"accessBoundary": boundary}
    assert 1195 < inj._expires - time.time() <= 1200


def test_gcp_route_fails_at_startup_without_a_host_login(auth, monkeypatch):
    auth({"gcs": {"type": "gcp-service-account"}})

    def no_login(scopes):
        raise proxy.google.auth.exceptions.DefaultCredentialsError("please log in")
    monkeypatch.setattr(proxy.google.auth, "default", no_login)
    with pytest.raises(RuntimeError, match="application-default login.*please log in"):
        proxy._Route({"name": "gcs", "upstream": "https://storage.googleapis.com", "auth": {"credential": "gcs"}})


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


AUTH = {"api": {"type": "api-key", "key": "k"}}


class Proxy:
    def __init__(self, dirpath, routes, auth=None, env=None):
        self.dir = dirpath
        (dirpath / "routes.json").write_text(json.dumps(routes))
        self.auth = dirpath / "auth.json"
        self.auth.write_text(json.dumps(AUTH if auth is None else auth))
        self.auth.chmod(0o600)
        args = [sys.executable, PROXY, "--auth-file", self.auth, dirpath / "routes.json", dirpath]
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
            "auth": {"credential": "api"}, **cfg}


def test_credentials_are_injected_and_the_clients_are_dropped(start, upstream):
    p = start([api_route(upstream)], auth={"api": {"type": "api-key", "key": "from-auth-json"}})
    resp, _ = p.request("GET", "/echo?q=1", headers={"Authorization": "Bearer placeholder",
                                                      "X-Api-Key": "placeholder", "X-Trace": "kept"})
    assert resp.status == 200
    [seen] = upstream.seen
    assert seen["path"] == "/echo?q=1"
    assert seen["headers"]["Authorization"] == "Bearer from-auth-json"
    assert "X-Api-Key" not in seen["headers"]
    assert seen["headers"]["X-Trace"] == "kept"
    assert seen["headers"]["Host"] == upstream.url.removeprefix("http://")


def test_urls_are_rewritten_both_ways(start, upstream):
    p = start([api_route(upstream)])
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
    p = start([api_route(upstream)])
    payload = b"http://127.0.0.1:18080"
    _, data = p.request("PUT", "/binary", body=payload, headers={"Content-Type": "application/octet-stream"})
    assert upstream.seen[0]["body"] == payload
    assert data == upstream.url.encode()


def test_request_body_rewrite_ignores_header_case(start, upstream):
    """Node's fetch sends lowercase header names; the rewritten body must still arrive whole."""
    p = start([api_route(upstream, localUrl="http://api.local")])
    body = '{"cb": "http://api.local/hook"}'
    p.request("POST", "/echo", body=body,
              headers={"content-type": "application/json", "content-length": str(len(body))})
    assert json.loads(upstream.seen[0]["body"]) == {"cb": f"{upstream.url}/hook"}


def test_allowlists_refuse_without_reaching_the_upstream(start, upstream):
    p = start([api_route(upstream, allowMethods=["GET"], allowPaths=["/echo"])])
    assert p.request("GET", "/echo")[0].status == 200
    for method, path in (("DELETE", "/echo"), ("GET", "/admin")):
        resp, data = p.request(method, path)
        assert resp.status == 403
        assert "not permitted" in json.loads(data)["error"]
    assert len(upstream.seen) == 1


def test_any_method_is_relayed_without_an_allowlist(start, upstream):
    p = start([api_route(upstream)])
    assert p.request("PURGE", "/echo")[0].status == 200
    assert upstream.seen[0]["method"] == "PURGE"


def test_oversized_bodies_are_refused(start, upstream):
    p = start([api_route(upstream, maxBodyBytes=10)])
    assert p.request("POST", "/echo", body=b"x" * 11)[0].status == 413
    assert p.request("POST", "/echo", body=b"x" * 10)[0].status == 200


def test_upstream_errors_pass_through(start, upstream):
    p = start([api_route(upstream)])
    resp, data = p.request("GET", "/missing")
    assert (resp.status, json.loads(data)) == (404, {"error": "nope"})


def test_unreachable_upstream_is_a_502(start):
    p = start([{"name": "api", "upstream": f"http://127.0.0.1:{free_port()}"}])
    resp, data = p.request("GET", "/")
    assert resp.status == 502 and "could not reach" in data.decode()


def test_a_credential_gone_since_the_start_is_a_502(start, upstream):
    p = start([api_route(upstream)])
    p.auth.write_text("{}")  # taken out of auth.json while the proxy runs
    resp, data = p.request("GET", "/echo")
    assert resp.status == 502 and "credentials" in data.decode()
    assert upstream.seen == []


def test_oauth2_route_mints_once_for_many_requests(start, upstream):
    p = start([api_route(upstream, auth={"credential": "idp"})],
              auth={"idp": {"type": "oauth2-client", "tokenUrl": f"{upstream.url}/token", "clientId": "i", "clientSecret": "s"}})
    p.request("GET", "/echo")
    p.request("GET", "/echo")
    assert [s["headers"]["Authorization"] for s in upstream.seen] == ["Bearer oauth-1"] * 2
    assert upstream.token_requests == 1


def test_each_route_gets_its_own_socket(start, upstream):
    p = start([api_route(upstream), {"name": "other", "upstream": upstream.url}])
    p.request("GET", "/echo", name="other")
    assert "Authorization" not in upstream.seen[0]["headers"]
    assert oct((p.dir / "other.sock").stat().st_mode & 0o777) == "0o666"


@pytest.mark.parametrize("routes, message", [
    ([{"name": "api", "upstream": "http://x", "allowMethods": []}], "allowMethods is empty"),
    ([{"name": "x" * 120, "upstream": "http://x"}], "socket path too long"),
    ([{"name": "api", "upstream": "http://x", "auth": {"credential": "nobody"}}],
     "route 'api': auth.credential 'nobody' needs the authentications file"),
])
def test_bad_routes_fail_the_start(short_tmp, routes, message):
    (short_tmp / "routes.json").write_text(json.dumps(routes))
    done = subprocess.run([sys.executable, PROXY, short_tmp / "routes.json", short_tmp],
                          capture_output=True, text=True, timeout=10)
    assert done.returncode != 0 and message in done.stderr
