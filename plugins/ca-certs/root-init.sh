# shellcheck shell=sh
# Root stage: fold the mounted certificates into the container's trust store. Runs as root
# because /usr/local/share/ca-certificates and the generated bundle are root-owned, and at
# priority 1 so every later stage (github-auth's token minting, the agent itself) already trusts
# the proxy.

# Normalize on the way in. update-ca-certificates only reads files named *.crt, and only
# understands PEM — but a host store may well hold DER-encoded certificates under a .crt name
# (Debian's own update-ca-certificates accepts them into the directory and then silently emits an
# unusable bundle entry). Convert whatever each file actually is into PEM.
_ca_count=0
for _src in /opt/ca-certs/*; do
  [ -f "$_src" ] || continue
  _dst="/usr/local/share/ca-certificates/$(basename "$_src" | sed 's/\.[^.]*$//').crt"
  if openssl x509 -in "$_src" -out "$_dst" 2>/dev/null \
     || openssl x509 -inform DER -in "$_src" -out "$_dst" 2>/dev/null; then
    _ca_count=$((_ca_count + 1))
  else
    echo "⚠️  Skipping $_src: not a certificate openssl can read" >&2
  fi
done
unset _src _dst

# Noisy on stderr ("skipping duplicate certificate") whenever the host store overlaps Debian's
# own, which is the normal case — quiet it, but let a real failure surface.
update-ca-certificates >/dev/null 2>&1 || echo "⚠️  update-ca-certificates failed" >&2

# Node ships its own compiled-in root store and ignores the system one, so the agents (both CLIs
# are Node programs) need this pointer as well; NODE_EXTRA_CA_CERTS is additive, so the bundle it
# names may safely be the full system one. The Python variables cover pip and the headroom proxy.
# These exports survive the `su -m node` handoff, so the agent user inherits them.
export NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt
export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

echo "✅ Trust store: added $_ca_count extra CA certificate(s)"
unset _ca_count
