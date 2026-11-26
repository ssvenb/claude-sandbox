#!/usr/bin/env bash
# The web UI behind oauth2-proxy (https://oauth2-proxy.github.io): Google sign-in, one email domain only.
#   serve-oauth.sh --host NAME [--port 4180] [--domain levatioai.com] [-- oauth2-proxy flag...]
# NAME is the name the page is opened by (the OAuth client's redirect URI is https://NAME/oauth2/callback),
# and *.NAME must reach the proxy too (DNS and the TLS certificate): the sessions' demo servers.
# oauth2-proxy reads its secrets from the environment: OAUTH2_PROXY_CLIENT_ID, OAUTH2_PROXY_CLIENT_SECRET,
# OAUTH2_PROXY_COOKIE_SECRET (any other flag as OAUTH2_PROXY_<FLAG> too, or after --).
# The server itself listens on 127.0.0.1:${SANDBOX_WEB_UPSTREAM_PORT:-8786} only: nothing but the proxy may reach it.
here=$(dirname "$(readlink -f "$0")")
host="" port=4180 domain=levatioai.com
while [ $# -gt 0 ]; do
  case "$1" in
    --host) host=$2; shift 2 ;;
    --port) port=$2; shift 2 ;;
    --domain) domain=$2; shift 2 ;;
    --) shift; break ;;
    *) echo "serve-oauth.sh: unknown argument $1 (oauth2-proxy's own flags go after --)" >&2; exit 2 ;;
  esac
done
[ -n "$host" ] || { echo "serve-oauth.sh: --host NAME is required" >&2; exit 2; }
command -v oauth2-proxy >/dev/null || { echo "❌ oauth2-proxy is required: https://github.com/oauth2-proxy/oauth2-proxy/releases" >&2; exit 1; }
for v in OAUTH2_PROXY_CLIENT_ID OAUTH2_PROXY_CLIENT_SECRET OAUTH2_PROXY_COOKIE_SECRET; do
  [ -n "${!v}" ] || { echo "serve-oauth.sh: $v is not set" >&2; exit 2; }
done
upstream=${SANDBOX_WEB_UPSTREAM_PORT:-8786}

# The sessions' demo servers are subdomains of NAME, <RUN_ID>-<port>.NAME, which the server relays
# to them (plugins/dev-server): the sign-in's cookie is the whole domain's, its callback NAME's alone.
# The cookie keeps the name the server takes it out by before a demo would see it.
export SANDBOX_WEB_SUBDOMAINS=1
"$here/serve.sh" --port "$upstream" --bind 127.0.0.1 --allow-host "$host" &
# The Host header passes through, so the server's Host and Origin checks see NAME.
oauth2-proxy --provider=google --email-domain="$domain" --skip-provider-button \
  --cookie-domain=".$host" --redirect-url="https://$host/oauth2/callback" \
  --http-address="0.0.0.0:$port" --upstream="http://127.0.0.1:$upstream/" "$@" --cookie-name=_oauth2_proxy &
trap 'kill $(jobs -p) 2>/dev/null' EXIT
trap 'exit 0' INT TERM
# Either one ending ends both, so a supervisor (systemd's Restart=) sees it and starts them again.
# A system unit run as a user (User=) gets no systemd scope for its sessions: give it KillMode=process, or a restart stops them.
wait -n
