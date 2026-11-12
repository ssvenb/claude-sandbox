"""The host-side credential minters: github-auth's mint-gh-token.py and gcp-auth's mint-gcp-token.py.

Both are run in-process with urlopen replaced by a fake API, so the requests they make can be
checked without the network. openssl (GitHub's JWT) and the gcloud stub run for real.
"""
import base64
import io
import json
import runpy
import subprocess
import urllib.error
import urllib.request

import pytest

from conftest import REPO

GH_MINT = REPO / "plugins/github-auth/host/mint-gh-token.py"
GCP_MINT = REPO / "plugins/gcp-auth/host/mint-gcp-token.py"


class FakeAPI:
    def __init__(self, monkeypatch, responses):
        self.responses = responses  # {(method, url): (status, body)}
        self.requests = []
        monkeypatch.setattr(urllib.request, "urlopen", self.urlopen)

    def urlopen(self, req, *args, **kwargs):
        self.requests.append(req)
        status, body = self.responses[(req.get_method(), req.full_url)]
        data = (body if isinstance(body, str) else json.dumps(body)).encode()
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "error", {}, io.BytesIO(data))
        return io.BytesIO(data)


def run(script):
    runpy.run_path(str(script), run_name="__main__")


@pytest.fixture(scope="module")
def app_key(tmp_path_factory):
    d = tmp_path_factory.mktemp("key")
    subprocess.run(["openssl", "genrsa", "-out", d / "key.pem", "2048"], check=True, capture_output=True)
    subprocess.run(["openssl", "rsa", "-in", d / "key.pem", "-pubout", "-out", d / "pub.pem"],
                   check=True, capture_output=True)
    return d


@pytest.fixture
def gh_env(monkeypatch, app_key):
    monkeypatch.setenv("GH_APP_ID", "4242")
    monkeypatch.setenv("GH_PRIVATE_KEY_FILE", str(app_key / "key.pem"))
    monkeypatch.delenv("GH_HOST", raising=False)
    monkeypatch.delenv("REPO_URL", raising=False)


def b64decode(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


API = "https://api.github.com"


@pytest.mark.parametrize("url", [
    "https://github.com/acme/widgets.git",
    "https://github.com/acme/widgets",
    "https://github.com/acme/widgets/",
    "git@github.com:acme/widgets.git",
    "https://x-access-token:t@github.com/acme/widgets.git",
])
def test_github_token_comes_from_the_installation_owning_the_repo(gh_env, monkeypatch, capsys, url):
    monkeypatch.setenv("REPO_URL", url)
    api = FakeAPI(monkeypatch, {
        ("GET", f"{API}/repos/acme/widgets/installation"): (200, {"id": 7}),
        ("POST", f"{API}/app/installations/7/access_tokens"): (201, {"token": "ghs_minted"}),
    })
    run(GH_MINT)
    assert capsys.readouterr().out == "ghs_minted\n"
    assert [r.get_method() for r in api.requests] == ["GET", "POST"]


def test_github_jwt_is_signed_by_the_app_key(gh_env, monkeypatch, app_key, tmp_path):
    api = FakeAPI(monkeypatch, {
        ("GET", f"{API}/app/installations"): (200, [{"id": 3}]),
        ("POST", f"{API}/app/installations/3/access_tokens"): (201, {"token": "t"}),
    })
    run(GH_MINT)
    jwt = api.requests[0].get_header("Authorization").removeprefix("Bearer ")
    header, payload, signature = jwt.split(".")
    assert json.loads(b64decode(header)) == {"alg": "RS256", "typ": "JWT"}
    claims = json.loads(b64decode(payload))
    assert claims["iss"] == "4242"
    assert claims["exp"] - claims["iat"] == 360  # backdated a minute, valid for five
    (tmp_path / "sig").write_bytes(b64decode(signature))
    (tmp_path / "input").write_text(f"{header}.{payload}")
    subprocess.run(["openssl", "dgst", "-sha256", "-verify", app_key / "pub.pem",
                    "-signature", tmp_path / "sig", tmp_path / "input"], check=True, capture_output=True)


def test_github_without_repo_url_takes_the_first_installation(gh_env, monkeypatch, capsys):
    FakeAPI(monkeypatch, {
        ("GET", f"{API}/app/installations"): (200, [{"id": 3}, {"id": 4}]),
        ("POST", f"{API}/app/installations/3/access_tokens"): (201, {"token": "first"}),
    })
    run(GH_MINT)
    assert capsys.readouterr().out == "first\n"


def test_github_enterprise_uses_the_v3_api(gh_env, monkeypatch, capsys):
    monkeypatch.setenv("GH_HOST", "ghe.example.com")
    monkeypatch.setenv("REPO_URL", "https://ghe.example.com/acme/widgets.git")
    base = "https://ghe.example.com/api/v3"
    FakeAPI(monkeypatch, {
        ("GET", f"{base}/repos/acme/widgets/installation"): (200, {"id": 9}),
        ("POST", f"{base}/app/installations/9/access_tokens"): (201, {"token": "ghe"}),
    })
    run(GH_MINT)
    assert capsys.readouterr().out == "ghe\n"


@pytest.mark.parametrize("responses, message", [
    ({("GET", f"{API}/app/installations"): (200, [])}, "has no installations"),
    ({("GET", f"{API}/app/installations"): (401, "bad creds")}, "GH_APP_ID must be the App ID"),
])
def test_github_failures_explain_themselves(gh_env, monkeypatch, responses, message):
    FakeAPI(monkeypatch, responses)
    with pytest.raises(SystemExit) as exc:
        run(GH_MINT)
    assert message in str(exc.value.code)


def test_github_app_not_installed_on_the_repo(gh_env, monkeypatch):
    monkeypatch.setenv("REPO_URL", "https://github.com/acme/widgets.git")
    FakeAPI(monkeypatch, {("GET", f"{API}/repos/acme/widgets/installation"): (404, "Not Found")})
    with pytest.raises(SystemExit) as exc:
        run(GH_MINT)
    assert "HTTP 404" in exc.value.code and "not installed" in exc.value.code


SA = "sandbox@proj.iam.gserviceaccount.com"
IAM = f"https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{SA}:generateAccessToken"


@pytest.fixture
def gcloud(monkeypatch, tmp_path):
    def make(script):
        path = tmp_path / "gcloud"
        path.write_text("#!/bin/sh\n" + script)
        path.chmod(0o755)
        monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    monkeypatch.setenv("GCP_SERVICE_ACCOUNT", SA)
    return make


def test_gcp_token_is_minted_for_the_service_account_with_the_host_login(gcloud, monkeypatch, capsys):
    gcloud('[ "$*" = "auth print-access-token --quiet" ] && echo host-user-token')
    api = FakeAPI(monkeypatch, {("POST", IAM): (200, {"accessToken": "sa-token"})})
    run(GCP_MINT)
    assert capsys.readouterr().out == "sa-token\n"
    [req] = api.requests
    assert req.get_header("Authorization") == "Bearer host-user-token"
    assert json.loads(req.data) == {"scope": ["https://www.googleapis.com/auth/cloud-platform"],
                                    "lifetime": "3600s"}


def test_gcp_without_a_host_login_says_how_to_log_in(gcloud):
    gcloud("echo 'not logged in' >&2; exit 1")
    with pytest.raises(SystemExit) as exc:
        run(GCP_MINT)
    assert "gcloud auth login" in exc.value.code and "not logged in" in exc.value.code


def test_gcp_credential_file_mints_through_gcloud_without_iam(gcloud, monkeypatch, capsys):
    gcloud('[ "$*" = "auth print-access-token --quiet" ] && echo "fed-$CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE"')
    monkeypatch.setenv("GCP_CREDENTIAL_FILE", "/etc/wif.json")
    api = FakeAPI(monkeypatch, {})
    run(GCP_MINT)
    assert capsys.readouterr().out == "fed-/etc/wif.json\n"
    assert api.requests == []


def test_gcp_credential_file_failure_names_the_file(gcloud, monkeypatch):
    gcloud("echo 'mTLS handshake failed' >&2; exit 1")
    monkeypatch.setenv("GCP_CREDENTIAL_FILE", "/etc/wif.json")
    with pytest.raises(SystemExit) as exc:
        run(GCP_MINT)
    assert "/etc/wif.json" in exc.value.code and "mTLS handshake failed" in exc.value.code


def test_gcp_missing_grant_names_the_role(gcloud, monkeypatch):
    gcloud("echo t")
    FakeAPI(monkeypatch, {("POST", IAM): (403, "denied")})
    with pytest.raises(SystemExit) as exc:
        run(GCP_MINT)
    assert "roles/iam.serviceAccountTokenCreator" in exc.value.code
