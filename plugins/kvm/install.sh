#!/bin/sh
# Build-time install (root, during docker build). QEMU for the image's own architecture, disk image
# tools, and cloud-image seeding (cloud-localds). No libvirt: its daemon wants far more privilege
# than a --device mount gives, and plain qemu-system covers what an agent needs.
set -eu

case "$(dpkg --print-architecture)" in
  amd64) _qemu=qemu-system-x86 ;;
  arm64) _qemu="qemu-system-arm qemu-efi-aarch64" ;;
  *)     _qemu=qemu-system ;;
esac

apt-get update
# shellcheck disable=SC2086
apt-get install -y --no-install-recommends $_qemu qemu-utils ovmf cloud-image-utils
rm -rf /var/lib/apt/lists/*
