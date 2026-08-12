#!/bin/sh
# Build-time install (root, during docker build). The OpenSSH client; the base image ships git
# but not ssh. Client only — nothing in the sandbox ever listens for connections.
set -eu

apt-get update
apt-get install -y --no-install-recommends openssh-client
rm -rf /var/lib/apt/lists/*
