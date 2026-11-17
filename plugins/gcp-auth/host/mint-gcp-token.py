#!/usr/bin/env python3
"""Mint a 1-hour access token for $GCP_SERVICE_ACCOUNT and print it to stdout.

Runs on the HOST, with your own gcloud login: that identity needs
roles/iam.serviceAccountTokenCreator on the service account, which in turn holds only what the
sandbox may do. Asks the IAM Credentials API directly rather than `gcloud auth print-access-token
--impersonate-service-account`, which may hand back a cached token with minutes left — the
container's metadata server reports the expiry as one hour from when this file was written.

With $GCP_CREDENTIAL_FILE (a workload identity federation config, e.g. X.509 from
`gcloud iam workload-identity-pools create-cred-config`) the host itself is the identity: gcloud
reads that file instead of any login, federates and impersonates the service account it names, and
its token is the one handed out. gcloud caches that token across runs (access_tokens.db) and only
renews it in its last 5 minutes, so it runs here against a scratch config dir that links to all of
yours except that cache: every mint is a fresh exchange with a full hour, as the metadata server
assumes.
"""
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

LIFETIME = 3600
ACCOUNT = os.environ["GCP_SERVICE_ACCOUNT"]
CRED_FILE = os.environ.get("GCP_CREDENTIAL_FILE")


def print_access_token(env=None):
    return subprocess.run(["gcloud", "auth", "print-access-token", "--quiet"], capture_output=True,
                          text=True, env=env)


if CRED_FILE:
    user_config = os.environ.get("CLOUDSDK_CONFIG") or os.path.expanduser("~/.config/gcloud")
    with tempfile.TemporaryDirectory(prefix="gcp-auth-") as config:
        # Properties, certificate_config.json and the rest stay yours; only the token cache is new.
        if os.path.isdir(user_config):
            for name in os.listdir(user_config):
                if name != "access_tokens.db":
                    os.symlink(os.path.join(user_config, name), os.path.join(config, name))
        done = print_access_token(dict(os.environ, CLOUDSDK_CONFIG=config,
                                       CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE=CRED_FILE))
else:
    done = print_access_token()
if CRED_FILE:
    if done.returncode != 0:
        sys.exit(f"mint-gcp-token: gcloud could not federate with {CRED_FILE}.\n{done.stderr.strip()}")
    print(done.stdout.strip())
else:
    if done.returncode != 0:
        sys.exit(f"mint-gcp-token: gcloud auth print-access-token failed — run `gcloud auth login` on the "
                 f"host.\n{done.stderr.strip()}")

    req = urllib.request.Request(
        f"https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/{ACCOUNT}:generateAccessToken",
        data=json.dumps({"scope": ["https://www.googleapis.com/auth/cloud-platform"],
                         "lifetime": f"{LIFETIME}s"}).encode(),
        headers={"Authorization": f"Bearer {done.stdout.strip()}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            print(json.load(resp)["accessToken"])
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace").strip()
        hint = ""
        if e.code in (403, 404):
            hint = (f"\nYour gcloud account needs roles/iam.serviceAccountTokenCreator on {ACCOUNT}, "
                    "and the IAM Service Account Credentials API must be enabled in its project.")
        sys.exit(f"mint-gcp-token: generateAccessToken failed: HTTP {e.code} {detail}{hint}")
