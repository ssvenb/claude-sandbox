#!/bin/sh
# Build-time install (root, during docker build). AWS CLI v2, from Amazon's official installer —
# Debian's repos carry v1 only, and v2 is what supports the AWS_ENDPOINT_URL / config-file
# endpoint settings this plugin relies on for S3-compatible backends.
set -eu

case "$(dpkg --print-architecture)" in
  amd64) AWS_ARCH=x86_64 ;;
  arm64) AWS_ARCH=aarch64 ;;
  *) echo "s3-auth: unsupported architecture $(dpkg --print-architecture)" >&2; exit 1 ;;
esac

apt-get update
apt-get install -y --no-install-recommends unzip
rm -rf /var/lib/apt/lists/*

tmp=$(mktemp -d)
curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-${AWS_ARCH}.zip" -o "$tmp/awscliv2.zip"
unzip -q "$tmp/awscliv2.zip" -d "$tmp"
# Isolated install dir, only the entrypoints linked onto PATH (same shape as the headroom venv).
"$tmp/aws/install" --install-dir /opt/aws-cli --bin-dir /usr/local/bin
rm -rf "$tmp"
