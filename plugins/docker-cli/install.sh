#!/bin/sh
# Build-time install (root, during docker build). Docker Engine + CLI + compose and buildx from
# Docker's official apt repo. The daemon runs inside the sandbox, which host.sh starts under Sysbox.
set -eu

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
    > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y --no-install-recommends docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin
rm -rf /var/lib/apt/lists/*

# The classic overlay2 store: the containerd image store (the default since Docker 29) keeps every
# image's compressed blobs next to its unpacked layers, about twice the disk for the same build.
mkdir -p /etc/docker
echo '{"features":{"containerd-snapshotter":false}}' > /etc/docker/daemon.json

# The daemon's socket is root:docker 0660; the agent user drives it through the group.
usermod -aG docker node
