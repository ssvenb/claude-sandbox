#!/bin/sh
# Build-time fixtures for the e2e image: what run.sh and the host would otherwise provide.
set -eu

# An origin for git-workspace: main, plus the branch of an earlier run to resume.
git init -q --bare -b main /srv/origin.git
git clone -q /srv/origin.git /tmp/seed 2>/dev/null
cd /tmp/seed
git -c user.name=seed -c user.email=seed@e2e commit -q --allow-empty -m "initial"
git push -q origin HEAD:main
git -c user.name=seed -c user.email=seed@e2e commit -q --allow-empty -m "previous work"
git push -q origin HEAD:refs/heads/claude-code/20251231-dead01
cd /
rm -rf /tmp/seed
chown -R node:node /srv/origin.git

# The credentials run.sh mints on the host and mounts at /run/credentials.
mkdir -p /run/credentials
echo ghs_e2e >/run/credentials/github-token
echo ya29.e2e >/run/credentials/gcp-token
chmod 644 /run/credentials/*

# ca-certs: a PEM and a DER certificate, and a file that is neither.
mkdir -p /opt/ca-certs
openssl req -x509 -newkey rsa:2048 -nodes -subj "/CN=Sandbox E2E PEM CA" -days 30 \
  -keyout /dev/null -out /opt/ca-certs/e2e-pem.crt 2>/dev/null
openssl req -x509 -newkey rsa:2048 -nodes -subj "/CN=Sandbox E2E DER CA" -days 30 \
  -keyout /dev/null -outform DER -out /opt/ca-certs/e2e-der.cer 2>/dev/null
echo "not a certificate" >/opt/ca-certs/README

