# shellcheck shell=bash
# Host stage: hand the container the extra root certificates this machine trusts.
#
# Needed wherever egress passes through a TLS-intercepting proxy: the host has the proxy's root
# CA installed, the image ships only Debian's default bundle, so every HTTPS call from inside the
# container fails with "self-signed certificate in certificate chain". Nothing here is secret —
# these are public root certificates, mounted read-only.

CA_CERTS_DIR="${CA_CERTS_DIR:-/usr/local/share/ca-certificates}"
[ -d "$CA_CERTS_DIR" ] \
  || die "CA_CERTS_DIR not found: $CA_CERTS_DIR (set it in .env, or disable the plugin with ENABLE_CA_CERTS=0)"
[ -n "$(find "$CA_CERTS_DIR" -maxdepth 1 -type f -print -quit)" ] \
  || die "No certificates in $CA_CERTS_DIR — nothing for the ca-certs plugin to install."

pass_mount "$CA_CERTS_DIR" /opt/ca-certs ro
