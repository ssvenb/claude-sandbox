#!/bin/sh
# Build-time install (root, during docker build). libvirt client tools only: the daemon is the
# host's, reached via a mounted socket, and the VMs it starts run on the host, not in here.
set -eu

apt-get update
apt-get install -y --no-install-recommends libvirt-clients
rm -rf /var/lib/apt/lists/*
