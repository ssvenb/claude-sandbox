#!/usr/bin/env python3
"""Mint a 1-hour access token for $GCP_SERVICE_ACCOUNT and print it to stdout.

Runs on the HOST, as your application default credentials (`gcloud auth application-default
login`): that identity needs roles/iam.serviceAccountTokenCreator on the service account, which in
turn holds only what the sandbox may do. Every mint is a fresh generateAccessToken call with a full
hour, as the container's metadata server assumes.

With $GCP_CREDENTIAL_FILE (a workload identity federation config, e.g. X.509 from
`gcloud iam workload-identity-pools create-cred-config`) the host itself is the identity: that
file is read instead of any login, federated, and the service account it names impersonated.
"""
import os
import sys

import google.auth
import google.auth.exceptions
from google.auth import identity_pool, impersonated_credentials
from google.auth.transport.requests import Request

LIFETIME = 3600
SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
ACCOUNT = os.environ["GCP_SERVICE_ACCOUNT"]
CRED_FILE = os.environ.get("GCP_CREDENTIAL_FILE")

try:
    if CRED_FILE:
        creds = identity_pool.Credentials.from_file(CRED_FILE, scopes=SCOPES)
    else:
        source, _ = google.auth.default(scopes=SCOPES)
        creds = impersonated_credentials.Credentials(source_credentials=source, target_principal=ACCOUNT,
                                                     target_scopes=SCOPES, lifetime=LIFETIME)
    creds.refresh(Request())
except (ValueError, OSError) as e:  # not an identity pool config, or not one at all
    if not CRED_FILE:
        raise
    sys.exit(f"mint-gcp-token: could not read {CRED_FILE}.\n{e}")
except google.auth.exceptions.DefaultCredentialsError as e:
    sys.exit(f"mint-gcp-token: no Google login on the host — run `gcloud auth application-default login`.\n{e}")
except google.auth.exceptions.GoogleAuthError as e:
    if CRED_FILE:
        sys.exit(f"mint-gcp-token: could not federate with {CRED_FILE}.\n{e}")
    sys.exit(f"mint-gcp-token: generateAccessToken failed: {e}\nYour Google account needs "
             f"roles/iam.serviceAccountTokenCreator on {ACCOUNT}, and the IAM Service Account "
             "Credentials API must be enabled in its project.")
print(creds.token)
