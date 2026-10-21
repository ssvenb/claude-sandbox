#!/usr/bin/env python3
"""Mint a 1-hour access token for $GCP_SERVICE_ACCOUNT and print it to stdout.

Runs on the HOST, with your own gcloud login: that identity needs
roles/iam.serviceAccountTokenCreator on the service account, which in turn holds only what the
sandbox may do. Asks the IAM Credentials API directly rather than `gcloud auth print-access-token
--impersonate-service-account`, which may hand back a cached token with minutes left — the
container's metadata server reports the expiry as one hour from when this file was written.
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

LIFETIME = 3600
ACCOUNT = os.environ["GCP_SERVICE_ACCOUNT"]

done = subprocess.run(["gcloud", "auth", "print-access-token", "--quiet"], capture_output=True, text=True)
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
