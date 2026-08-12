#!/bin/sh
# Build-time install (root, during docker build). The NetBird client plus the kernel-networking
# tools it drives. Each sandbox runs its OWN client (see root-init.sh) on the container's network
# namespace, so mesh traffic never flows through the host's peer. The release tarball ships a
# static Go binary; the version is pinned here — bump it and rebuild.
set -eu

NETBIRD_VERSION=0.72.4

case "$(dpkg --print-architecture)" in
  amd64) NB_ARCH=amd64 ;;
  arm64) NB_ARCH=arm64 ;;
  *) echo "netbird: unsupported architecture $(dpkg --print-architecture)" >&2; exit 1 ;;
esac

apt-get update
# WireGuard is created in-kernel via the tun device; iptables/iproute2 are what the client uses
# to install its routes and firewall rules.
apt-get install -y --no-install-recommends iptables iproute2
rm -rf /var/lib/apt/lists/*

curl -fsSL "https://github.com/netbirdio/netbird/releases/download/v${NETBIRD_VERSION}/netbird_${NETBIRD_VERSION}_linux_${NB_ARCH}.tar.gz" \
  | tar -xz -C /usr/local/bin netbird
chmod 555 /usr/local/bin/netbird
