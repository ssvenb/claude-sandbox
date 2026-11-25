#!/bin/sh
# Build-time install (root, during docker build): sudo, and what the tools in $PERMISSIONS_TOOLS
# (a build arg, validated on the host) need that the image lacks.
set -eu

pkgs=sudo
for tool in ${PERMISSIONS_TOOLS:-}; do
  case $tool in
    pip) pkgs="$pkgs python3-pip" ;;
    network) pkgs="$pkgs iproute2 iptables" ;;
    tcpdump|strace) pkgs="$pkgs $tool" ;;
  esac
done
apt-get update
# shellcheck disable=SC2086  # one argument per package
apt-get install -y --no-install-recommends $pkgs
rm -rf /var/lib/apt/lists/*
