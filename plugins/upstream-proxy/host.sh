# shellcheck shell=bash
# Host stage. Starts one credential-injecting reverse proxy per route, on YOUR machine, and hands
# the container nothing but the unix sockets they listen on — the API keys stay in this process's
# environment and are never passed to `docker run`.
#
# Routes are per-project, from the config file in the directory you launched from:
#
#   { "plugins": { "upstream-proxy": { "routes": [ ... ], "envFile": ".env" } } }
#
# No routes → the plugin does nothing, which is why it can stay on by default.

UPSTREAM_PROXY_ROUTES_JSON=$(plugin_config_json '.routes' '[]')
printf '%s' "$UPSTREAM_PROXY_ROUTES_JSON" | jq -e 'type == "array"' >/dev/null 2>&1 \
  || die "upstream-proxy: .plugins[\"upstream-proxy\"].routes in '$PROJECT_CONFIG_FILE' must be an array."

if [ "$(printf '%s' "$UPSTREAM_PROXY_ROUTES_JSON" | jq 'length')" = 0 ]; then
  echo "ℹ️  upstream-proxy: no routes configured in '$PROJECT_CONFIG_FILE'; nothing proxied."
  return 0
fi

# proxy.py takes a file; keep the routes out of the process table and drop them with the run.
UPSTREAM_PROXY_DIR=$(mktemp -d -t upstream-proxy-XXXXXX)
chmod 755 "$UPSTREAM_PROXY_DIR"
UPSTREAM_PROXY_SOCK_DIR="$UPSTREAM_PROXY_DIR/sockets"
mkdir -m 755 "$UPSTREAM_PROXY_SOCK_DIR"
UPSTREAM_PROXY_ROUTE_FILE="$UPSTREAM_PROXY_DIR/routes.json"
printf '%s' "$UPSTREAM_PROXY_ROUTES_JSON" >"$UPSTREAM_PROXY_ROUTE_FILE"

# The credentials a route names usually live in the target repo's own .env, which run.sh never
# sources. Hand the path to the proxy and let IT read the file: sourcing here would put the secrets
# in run.sh's environment, one stray pass_env away from the container. "envFile" (relative to
# $HOST_CWD) overrides; /dev/null loads nothing.
UPSTREAM_PROXY_ENV_FILE=$(plugin_config '.envFile' ".env")
case "$UPSTREAM_PROXY_ENV_FILE" in /*|"") ;; *) UPSTREAM_PROXY_ENV_FILE="$HOST_CWD/$UPSTREAM_PROXY_ENV_FILE" ;; esac
UPSTREAM_PROXY_ENV_ARGS=()
if [ -n "$UPSTREAM_PROXY_ENV_FILE" ] && [ -f "$UPSTREAM_PROXY_ENV_FILE" ]; then
  UPSTREAM_PROXY_ENV_ARGS=(--env-file "$UPSTREAM_PROXY_ENV_FILE")
elif [ -n "$UPSTREAM_PROXY_ENV_FILE" ] && [ "$UPSTREAM_PROXY_ENV_FILE" != /dev/null ]; then
  echo "ℹ️  upstream-proxy: no env file at '$UPSTREAM_PROXY_ENV_FILE'; routes must resolve from the host environment." >&2
fi

"$PLUGIN_DIR/host/proxy.py" \
  ${UPSTREAM_PROXY_ENV_ARGS[@]+"${UPSTREAM_PROXY_ENV_ARGS[@]}"} \
  "$UPSTREAM_PROXY_ROUTE_FILE" "$UPSTREAM_PROXY_SOCK_DIR" &
UPSTREAM_PROXY_PID=$!

# run.sh's last statement is `docker run`, so an EXIT trap fires once the agent's session ends.
# shellcheck disable=SC2064  # expand the pid and path now, not at trap time
trap "kill $UPSTREAM_PROXY_PID 2>/dev/null; rm -rf '$UPSTREAM_PROXY_DIR'" EXIT

# Wait for every socket rather than racing the container's socat forwarders.
for _ in $(seq 1 50); do
  missing=0
  while read -r name; do
    [ -S "$UPSTREAM_PROXY_SOCK_DIR/$name.sock" ] || missing=1
  done < <(jq -r '.[].name' "$UPSTREAM_PROXY_ROUTE_FILE")
  [ "$missing" = 0 ] && break
  kill -0 "$UPSTREAM_PROXY_PID" 2>/dev/null || die "upstream-proxy: the proxy exited during startup."
  sleep 0.1
done
[ "${missing:-1}" = 0 ] || die "upstream-proxy: sockets did not appear in $UPSTREAM_PROXY_SOCK_DIR."

pass_mount "$UPSTREAM_PROXY_SOCK_DIR" /run/upstream-proxy

# name:port pairs drive the container-side socat forwarders in root-init.sh.
pass_value UPSTREAM_PROXY_PORTS "$(jq -r '[.[] | "\(.name):\(.port)"] | join(" ")' "$UPSTREAM_PROXY_ROUTE_FILE")"

# Each route declares the env the agent should see: endpoints pointed at loopback, and placeholder
# credentials for SDKs that insist on one. The real values never leave this host.
while IFS=$'\t' read -r key value; do
  pass_value "$key" "$value"
done < <(jq -r '.[] | (.containerEnv // {}) | to_entries[] | "\(.key)\t\(.value)"' "$UPSTREAM_PROXY_ROUTE_FILE")

echo "🔒 upstream-proxy: $(jq -r '[.[].name] | join(", ")' "$UPSTREAM_PROXY_ROUTE_FILE") proxied from the host"
