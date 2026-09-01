#!/bin/sh
# Image build, root. socat is the container half of the bridge: it turns each bind-mounted unix
# socket into a loopback TCP port, so ordinary HTTP clients (httpx, openai, requests) need no
# unix-socket support of their own.
set -eu
apt-get update
apt-get install -y --no-install-recommends socat
rm -rf /var/lib/apt/lists/*
