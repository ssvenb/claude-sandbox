"""plugins/gcp-auth/root/metadata.py: the stand-in GCE metadata server."""
import http.client
import json
import os
import threading
import time
from http.server import HTTPServer

import pytest

from conftest import load

metadata = load("plugins/gcp-auth/root/metadata.py")
SA = "sandbox@proj.iam.gserviceaccount.com"
V1 = "/computeMetadata/v1/"


@pytest.fixture
def token_file(tmp_path):
    path = tmp_path / "gcp-token"
    path.write_text("ya29.token\n")
    return path


def serve(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def server(token_file):
    s = serve(HTTPServer(("127.0.0.1", 0), metadata.handler_for(str(token_file), SA, "proj")))
    yield s
    s.shutdown()


def get(server, path, method="GET", flavor=True):
    conn = http.client.HTTPConnection(*server.server_address, timeout=5)
    conn.request(method, path, headers={"Metadata-Flavor": "Google"} if flavor else {})
    resp = conn.getresponse()
    body = resp.read().decode()
    conn.close()
    return resp, body


def test_requests_without_the_flavor_header_are_refused(server):
    resp, _ = get(server, V1 + "project/project-id", flavor=False)
    assert resp.status == 403


def test_gce_detection_ping(server):
    resp, body = get(server, "/")
    assert (resp.status, body, resp.getheader("Metadata-Flavor")) == (200, "computeMetadata/\n", "Google")


@pytest.mark.parametrize("path, expected", [
    ("project/project-id", "proj"),
    ("universe/universe-domain", "googleapis.com"),
    ("instance/service-accounts/default/email", SA),
    (f"instance/service-accounts/{SA}/email", SA),
    ("instance/service-accounts/default/aliases", "default"),
    ("instance/service-accounts/default/scopes", "https://www.googleapis.com/auth/cloud-platform\n"),
    ("instance/service-accounts/", f"default/\n{SA}/\n"),
])
def test_identity_endpoints(server, path, expected):
    resp, body = get(server, V1 + path)
    assert (resp.status, body) == (200, expected)


def test_token_expiry_counts_from_when_the_host_wrote_the_file(server, token_file):
    written = time.time() - 600
    os.utime(token_file, (written, written))
    resp, body = get(server, V1 + "instance/service-accounts/default/token")
    token = json.loads(body)
    assert resp.getheader("Content-Type") == "application/json"
    assert token["access_token"] == "ya29.token" and token["token_type"] == "Bearer"
    assert 2990 <= token["expires_in"] <= 3000


def test_a_stale_token_reports_no_time_left(server, token_file):
    os.utime(token_file, (time.time() - 7200,) * 2)
    _, body = get(server, V1 + f"instance/service-accounts/{SA}/token")
    assert json.loads(body)["expires_in"] == 0


def test_recursive_listing(server):
    _, body = get(server, V1 + "instance/service-accounts/?recursive=true")
    accounts = json.loads(body)
    assert set(accounts) == {"default", SA}
    assert accounts["default"]["email"] == SA


@pytest.mark.parametrize("path", [V1 + "instance/hostname", "/other", V1 + "instance/service-accounts/x/email"])
def test_unknown_paths_are_404(server, path):
    assert get(server, path)[0].status == 404


def test_missing_token_file_is_503(server, token_file):
    token_file.unlink()
    assert get(server, V1 + "instance/service-accounts/default/token")[0].status == 503


def test_head_has_no_body(server):
    resp, body = get(server, V1 + "project/project-id", method="HEAD")
    assert (resp.status, body, resp.getheader("Content-Length")) == (200, "", "4")


@pytest.mark.parametrize("ours", [True, False])
def test_only_this_sandboxs_processes_are_answered(monkeypatch, token_file, ours):
    monkeypatch.setattr(metadata, "from_this_sandbox", lambda peer, local: ours)
    s = serve(metadata.Server((metadata.LOOPBACK, 0), metadata.handler_for(str(token_file), SA, "proj")))
    try:
        if ours:
            assert get(s, V1 + "project/project-id")[1] == "proj"
        else:
            with pytest.raises((http.client.RemoteDisconnected, ConnectionResetError)):
                get(s, V1 + "project/project-id")
    finally:
        s.shutdown()
