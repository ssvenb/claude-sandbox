#!/bin/sh
# Build-time install (root). The Google Cloud CLI, so the agent has gcloud ready to use; the
# client libraries the agent installs itself need nothing from here.
set -eu

curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
    | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
chmod go+r /usr/share/keyrings/cloud.google.gpg
echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
    > /etc/apt/sources.list.d/google-cloud-sdk.list
apt-get update
apt-get install -y --no-install-recommends google-cloud-cli
rm -rf /var/lib/apt/lists/*
