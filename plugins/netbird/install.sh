#!/bin/sh
# Build-time install (root, during docker build). The NetBird client (a static Go binary from the
# release tarball, pinned here) plus the kernel-networking tools it drives to install its routes
# and firewall rules. Each sandbox runs its OWN client, so mesh traffic never flows through the
# host's peer.
set -eu

NETBIRD_VERSION=0.72.4

case "$(dpkg --print-architecture)" in
  amd64) NB_ARCH=amd64 ;;
  arm64) NB_ARCH=arm64 ;;
  *) echo "netbird: unsupported architecture $(dpkg --print-architecture)" >&2; exit 1 ;;
esac

apt-get update
apt-get install -y --no-install-recommends iptables iproute2
rm -rf /var/lib/apt/lists/*

curl -fsSL "https://github.com/netbirdio/netbird/releases/download/v${NETBIRD_VERSION}/netbird_${NETBIRD_VERSION}_linux_${NB_ARCH}.tar.gz" \
  | tar -xz -C /usr/local/bin netbird
chmod 555 /usr/local/bin/netbird
