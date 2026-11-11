# shellcheck shell=bash
# Host stage: hand the container the extra root certificates this machine trusts, for networks
# behind a TLS-intercepting proxy (the image ships only Debian's bundle, so every HTTPS call from
# inside fails with "self-signed certificate in certificate chain"). Public certs, mounted ro.

CA_CERTS_DIR="${CA_CERTS_DIR:-/usr/local/share/ca-certificates}"
[ -d "$CA_CERTS_DIR" ] \
  || die "CA_CERTS_DIR not found: $CA_CERTS_DIR (set it in .env, or disable the plugin with ENABLE_CA_CERTS=0)"

# The build needs them as well (curl/apt/npm/pip during `docker build`), as one PEM bundle;
# DER files are converted here for the same reason root-init.sh does, and anything else is
# skipped as it is there.
_ca_pem=""
for _src in "$CA_CERTS_DIR"/*; do
  [ -f "$_src" ] || continue
  _cert=$(openssl x509 -in "$_src" 2>/dev/null || openssl x509 -inform DER -in "$_src" 2>/dev/null) \
    || { echo "⚠️  ca-certs: skipping $_src: not a certificate openssl can read" >&2; continue; }
  _ca_pem+=$_cert$'\n'
done
[ -n "$_ca_pem" ] \
  || die "No certificates in $CA_CERTS_DIR — nothing for the ca-certs plugin to install."

pass_mount "$CA_CERTS_DIR" /opt/ca-certs ro
pass_build_arg EXTRA_CA_CERTS "$_ca_pem"
unset _src _cert _ca_pem
