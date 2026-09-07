# shellcheck shell=bash
# Host stage: hand the container the extra root certificates this machine trusts, for networks
# behind a TLS-intercepting proxy (the image ships only Debian's bundle, so every HTTPS call from
# inside fails with "self-signed certificate in certificate chain"). Public certs, mounted ro.

CA_CERTS_DIR="${CA_CERTS_DIR:-/usr/local/share/ca-certificates}"
[ -d "$CA_CERTS_DIR" ] \
  || die "CA_CERTS_DIR not found: $CA_CERTS_DIR (set it in .env, or disable the plugin with ENABLE_CA_CERTS=0)"
[ -n "$(find "$CA_CERTS_DIR" -maxdepth 1 -type f -print -quit)" ] \
  || die "No certificates in $CA_CERTS_DIR — nothing for the ca-certs plugin to install."

pass_mount "$CA_CERTS_DIR" /opt/ca-certs ro
