"""The host-side credential minters: github-auth's mint-gh-token.py and gcp-auth's mint-gcp-token.py.

Both are run in-process against a fake API (urlopen for GitHub, requests for google-auth), so the
requests they make can be checked without the network; PyJWT and google-auth run for real.
"""
import io
import json
import os
import runpy
import urllib.error
import urllib.parse
import urllib.request

import jwt as pyjwt
import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

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
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    (d / "key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                                  serialization.NoEncryption()))
    (d / "pub.pem").write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,
                                                              serialization.PublicFormat.SubjectPublicKeyInfo))
    return d


@pytest.fixture
def gh_env(monkeypatch, app_key):
    monkeypatch.setenv("GH_APP_ID", "4242")
    monkeypatch.setenv("GH_PRIVATE_KEY_FILE", str(app_key / "key.pem"))
    monkeypatch.delenv("GH_HOST", raising=False)
    monkeypatch.delenv("REPO_URL", raising=False)


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


def test_github_jwt_is_signed_by_the_app_key(gh_env, monkeypatch, app_key):
    api = FakeAPI(monkeypatch, {
        ("GET", f"{API}/app/installations"): (200, [{"id": 3}]),
        ("POST", f"{API}/app/installations/3/access_tokens"): (201, {"token": "t"}),
    })
    run(GH_MINT)
    jwt = api.requests[0].get_header("Authorization").removeprefix("Bearer ")
    assert pyjwt.get_unverified_header(jwt)["alg"] == "RS256"
    claims = pyjwt.decode(jwt, (app_key / "pub.pem").read_bytes(), algorithms=["RS256"])  # checks the signature
    assert claims["iss"] == "4242"
    assert claims["exp"] - claims["iat"] == 360  # backdated a minute, valid for five


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
OAUTH = "https://oauth2.googleapis.com/token"
STS = "https://sts.googleapis.com/v1/token"
SA_TOKEN = {"accessToken": "sa-token", "expireTime": "2099-01-01T00:00:00Z"}


@pytest.fixture
def google(monkeypatch, tmp_path):
    """google-auth's HTTP faked: set .responses {(method, url): (status, body)}; read .requests
    (method, url, headers, body). No login of the host's, no GCE metadata server."""
    def request(session, method, url, data=None, headers=None, **kw):
        if (method, url) not in fake.responses:  # the GCE metadata server, say: not on this host
            raise requests.ConnectionError(f"{method} {url}: nothing here")
        fake.requests.append((method, url, headers or {}, data))
        status, body = fake.responses[(method, url)]
        r = requests.Response()
        r.status_code, r._content, r.headers["Content-Type"] = status, json.dumps(body).encode(), "application/json"
        return r
    fake = type("Google", (), {"responses": {}, "requests": []})()
    monkeypatch.setattr(requests.Session, "request", request)
    monkeypatch.setenv("GCP_SERVICE_ACCOUNT", SA)
    monkeypatch.setenv("CLOUDSDK_CONFIG", str(tmp_path / "no-gcloud"))
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.delenv("GCP_CREDENTIAL_FILE", raising=False)
    return fake


@pytest.fixture
def adc(monkeypatch, tmp_path):
    """The host's application default credentials: a user login (gcloud auth application-default login)."""
    path = tmp_path / "adc.json"
    path.write_text(json.dumps({"type": "authorized_user", "client_id": "c", "client_secret": "s", "refresh_token": "r"}))
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(path))


def body(data):
    return json.loads(data) if data and data[:1] in ("{", b"{") else dict(urllib.parse.parse_qsl(data.decode() if isinstance(data, bytes) else data))


def test_gcp_token_is_minted_for_the_service_account_with_the_host_login(google, adc, capsys):
    google.responses = {("POST", OAUTH): (200, {"access_token": "host-user-token", "expires_in": 3600}),
                        ("POST", IAM): (200, SA_TOKEN)}
    run(GCP_MINT)
    assert capsys.readouterr().out == "sa-token\n"
    _, (method, url, headers, data) = google.requests
    assert headers["authorization"] == "Bearer host-user-token"
    assert {k: v for k, v in body(data).items() if k != "delegates"} == {
        "scope": ["https://www.googleapis.com/auth/cloud-platform"], "lifetime": "3600s"}


def test_gcp_without_a_host_login_says_how_to_log_in(google):
    with pytest.raises(SystemExit) as exc:
        run(GCP_MINT)
    assert "gcloud auth application-default login" in exc.value.code
    assert google.requests == []


def test_gcp_credential_file_federates_and_impersonates_the_account_it_names(google, capsys, monkeypatch, tmp_path):
    (tmp_path / "subject").write_text("host-identity")
    cred = tmp_path / "wif.json"
    cred.write_text(json.dumps({
        "type": "external_account", "audience": "//iam.googleapis.com/projects/1/locations/global/workloadIdentityPools/p/providers/x",
        "subject_token_type": "urn:ietf:params:oauth:token-type:jwt", "token_url": STS,
        "credential_source": {"file": str(tmp_path / "subject")}, "service_account_impersonation_url": IAM}))
    monkeypatch.setenv("GCP_CREDENTIAL_FILE", str(cred))
    google.responses = {("POST", STS): (200, {"access_token": "federated", "token_type": "Bearer", "expires_in": 3600,
                                             "issued_token_type": "urn:ietf:params:oauth:token-type:access_token"}),
                        ("POST", IAM): (200, SA_TOKEN)}
    run(GCP_MINT)
    assert capsys.readouterr().out == "sa-token\n"
    (_, _, _, sts), (_, _, headers, _) = google.requests  # a fresh exchange every mint: nothing cached
    assert body(sts)["subject_token"] == "host-identity"
    assert headers["authorization"] == "Bearer federated"


def test_gcp_credential_file_failure_names_the_file(google, monkeypatch, tmp_path):
    cred = tmp_path / "wif.json"
    cred.write_text("{}")
    monkeypatch.setenv("GCP_CREDENTIAL_FILE", str(cred))
    with pytest.raises(SystemExit) as exc:
        run(GCP_MINT)
    assert str(cred) in exc.value.code


def test_gcp_missing_grant_names_the_role(google, adc):
    google.responses = {("POST", OAUTH): (200, {"access_token": "t", "expires_in": 3600}),
                        ("POST", IAM): (403, {"error": {"message": "denied"}})}
    with pytest.raises(SystemExit) as exc:
        run(GCP_MINT)
    assert "roles/iam.serviceAccountTokenCreator" in exc.value.code and "denied" in exc.value.code


def test_github_key_that_is_no_key_says_why(gh_env, monkeypatch, tmp_path):
    key = tmp_path / "bad.pem"
    key.write_text("not a key\n")
    monkeypatch.setenv("GH_PRIVATE_KEY_FILE", str(key))
    with pytest.raises(SystemExit) as e:
        run(GH_MINT)
    msg = str(e.value)
    assert f"could not sign the App's JWT with {key}" in msg
    assert "PEM private key" in msg
    assert "Traceback" not in msg


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
def test_github_key_this_user_cannot_read_says_so(gh_env, monkeypatch, app_key, tmp_path):
    key = tmp_path / "locked.pem"
    key.write_bytes((app_key / "key.pem").read_bytes())
    key.chmod(0)
    monkeypatch.setenv("GH_PRIVATE_KEY_FILE", str(key))
    with pytest.raises(SystemExit) as e:
        run(GH_MINT)
    assert "is not readable by this user" in str(e.value)
