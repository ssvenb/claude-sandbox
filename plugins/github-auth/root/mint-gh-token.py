#!/usr/bin/env python3
"""Mint a short-lived GitHub App installation token and print it to stdout.

Root-only: reads the App key ($GH_PRIVATE_KEY, $GH_APP_ID), which never reach the
unprivileged 'node' user the agent runs as. Installation tokens are hard-capped at
1h by GitHub, so entrypoint.sh calls this at startup and on a refresh loop.
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

# GitHub Enterprise Server puts the REST API under /api/v3; github.com uses api.github.com.
GH_HOST = os.environ.get("GH_HOST") or "github.com"
API = "https://api.github.com" if GH_HOST == "github.com" else f"https://{GH_HOST}/api/v3"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def api(path: str, jwt: str, method: str = "GET"):
    req = urllib.request.Request(
        API + path,
        method=method,
        headers={"Authorization": f"Bearer {jwt}",
                 "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace").strip()
        hint = ""
        if e.code == 401:
            hint = ("\nGH_APP_ID must be the App ID (a number, from the App's settings page) "
                    "— not the Client ID or the installation ID — and GH_PRIVATE_KEY_FILE must "
                    "be a .pem generated for that same App. Also check the host clock.")
        sys.exit(f"mint-gh-token: {method} {path} failed: HTTP {e.code} {detail}{hint}")


# Build the RS256-signed JWT. openssl (already in the image) does the signing so we
# don't pull a Python crypto dependency into the container.
now = int(time.time())
header = b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
payload = b64url(json.dumps(
    {"iat": now - 60, "exp": now + 300, "iss": os.environ["GH_APP_ID"]}).encode())
signing_input = f"{header}.{payload}".encode()

with tempfile.NamedTemporaryFile("w", suffix=".pem") as pem:
    pem.write(os.environ["GH_PRIVATE_KEY"].rstrip("\n") + "\n")
    pem.flush()
    sig = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", pem.name],
        input=signing_input, capture_output=True, check=True).stdout
jwt = f"{signing_input.decode()}.{b64url(sig)}"

installations = api("/app/installations", jwt)
if not installations:
    sys.exit("mint-gh-token: the GitHub App has no installations; install it on the "
             "account or org that owns REPO_URL.")
installation_id = installations[0]["id"]
token = api(f"/app/installations/{installation_id}/access_tokens", jwt, "POST")["token"]
print(token)
