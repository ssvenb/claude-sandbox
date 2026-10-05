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

# The build needs them as well (curl/apt/npm/pip during `docker build`), as one PEM bundle;
# DER files are converted here for the same reason root-init.sh does.
_ca_pem=""
for _src in "$CA_CERTS_DIR"/*; do
  [ -f "$_src" ] || continue
  _ca_pem+=$(openssl x509 -in "$_src" 2>/dev/null || openssl x509 -inform DER -in "$_src" 2>/dev/null)$'\n'
done
pass_build_arg EXTRA_CA_CERTS "$_ca_pem"
unset _src _ca_pem
