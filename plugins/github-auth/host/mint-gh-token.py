#!/usr/bin/env python3
"""Mint a short-lived GitHub App installation token and print it to stdout.

Runs on the HOST: reads the App key from $GH_PRIVATE_KEY_FILE, which never enters the
container. Installation tokens are hard-capped at 1h by GitHub, so run.sh's credential
refresher (src/services/credentials/credentials.sh) calls this at startup and again every 40 minutes.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

import jwt as pyjwt

# GitHub Enterprise Server puts the REST API under /api/v3; github.com uses api.github.com.
GH_HOST = os.environ.get("GH_HOST") or "github.com"
API = "https://api.github.com" if GH_HOST == "github.com" else f"https://{GH_HOST}/api/v3"


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
        elif e.code == 404 and path.endswith("/installation"):
            hint = "\nThe GitHub App is not installed on REPO_URL's org, or not granted that repo."
        sys.exit(f"mint-gh-token: {method} {path} failed: HTTP {e.code} {detail}{hint}")


# The App's JWT, RS256-signed with its key; backdated a minute against clock skew.
key_file = os.environ["GH_PRIVATE_KEY_FILE"]
if not os.access(key_file, os.R_OK):
    sys.exit(f"mint-gh-token: {key_file} is not readable by this user (uid {os.getuid()}); run.sh signs with "
             "your own account, so make the key readable by it (e.g. chown it to you, mode 600).")
now = int(time.time())
try:
    with open(key_file, "rb") as f:
        jwt = pyjwt.encode({"iat": now - 60, "exp": now + 300, "iss": os.environ["GH_APP_ID"]}, f.read(), algorithm="RS256")
except (ValueError, TypeError, pyjwt.PyJWTError) as e:
    sys.exit(f"mint-gh-token: could not sign the App's JWT with {key_file}: {e}\n"
             "GH_PRIVATE_KEY_FILE must be the App's PEM private key, as downloaded from the "
             "App's settings page (\"-----BEGIN RSA PRIVATE KEY-----\"), without a passphrase.")

# The App may be installed on several orgs; a token from the wrong one sees REPO_URL as "not found".
repo = re.search(r"[/:]([^/:]+)/([^/]+?)(?:\.git)?/?$", os.environ.get("REPO_URL", ""))
if repo:
    installation_id = api(f"/repos/{repo[1]}/{repo[2]}/installation", jwt)["id"]
else:
    installations = api("/app/installations", jwt)
    if not installations:
        sys.exit("mint-gh-token: the GitHub App has no installations; install it on the "
                 "account or org that owns REPO_URL.")
    installation_id = installations[0]["id"]
token = api(f"/app/installations/{installation_id}/access_tokens", jwt, "POST")["token"]
print(token)
