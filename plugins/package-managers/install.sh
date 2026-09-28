#!/bin/sh
# Build-time install (root, during docker build). sudo only; the rule that lets the agent use it is
# written at boot by root-init.sh.
set -eu

apt-get update
apt-get install -y --no-install-recommends sudo
rm -rf /var/lib/apt/lists/*
