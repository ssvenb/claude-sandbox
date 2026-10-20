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

# Under host-network every sandbox on the machine shares the host's loopback, so the proxy itself
# listens on the route ports and each container only vouches for its own processes (see
# root/forward.py). Otherwise each container has a loopback of its own and bridges the sockets.
UPSTREAM_PROXY_HOST_NETWORK=0
case " $ENABLED_PLUGINS " in *" host-network "*) UPSTREAM_PROXY_HOST_NETWORK=1 ;; esac

# One proxy per project: every sandbox launched from this checkout with these routes shares it —
# under host-network it is the only thing that can hold their common ports — the first run starts
# it and the last one to exit stops it. A changed config or network mode gets a proxy of its own.
UPSTREAM_PROXY_KEY=$(printf '%s\n' "$HOST_CWD" "$UPSTREAM_PROXY_ENV_FILE" "$UPSTREAM_PROXY_HOST_NETWORK" \
  "$UPSTREAM_PROXY_ROUTES_JSON" | sha256sum | cut -c1-12)
UPSTREAM_PROXY_DIR="${TMPDIR:-/tmp}/upstream-proxy-$(id -u)-$UPSTREAM_PROXY_KEY"
mkdir -p -m 755 "$UPSTREAM_PROXY_DIR"
[ -O "$UPSTREAM_PROXY_DIR" ] && [ ! -L "$UPSTREAM_PROXY_DIR" ] \
  || die "upstream-proxy: '$UPSTREAM_PROXY_DIR' is not yours; remove it and run again."
UPSTREAM_PROXY_SOCK_DIR="$UPSTREAM_PROXY_DIR/sockets"
UPSTREAM_PROXY_ATTEST_DIR="$UPSTREAM_PROXY_DIR/attest"
# One file per run.sh using the proxy, named after its pid.
UPSTREAM_PROXY_USERS="$UPSTREAM_PROXY_DIR/users"
UPSTREAM_PROXY_PID_FILE="$UPSTREAM_PROXY_DIR/proxy.pid"
UPSTREAM_PROXY_ROUTE_FILE="$UPSTREAM_PROXY_DIR/routes.json"
# The proxy logs a line per request; run.sh shares its terminal with the agent's TUI, so send that
# to a file instead of into the agent's input field.
UPSTREAM_PROXY_LOG="$UPSTREAM_PROXY_DIR/proxy.log"

# A run killed before its exit hook leaves its file behind; a dead pid holds nothing.
upstream_proxy_prune() {
  local f
  for f in "$UPSTREAM_PROXY_USERS"/*; do
    [ -e "$f" ] || continue
    kill -0 "${f##*/}" 2>/dev/null || rm -f "$f"
  done
}

upstream_proxy_release() {
  local fd
  exec {fd}>"$UPSTREAM_PROXY_DIR/lock"
  flock "$fd"
  rm -f "$UPSTREAM_PROXY_USERS/$$"
  upstream_proxy_prune
  if ! compgen -G "$UPSTREAM_PROXY_USERS/*" >/dev/null; then
    kill "$(cat "$UPSTREAM_PROXY_PID_FILE" 2>/dev/null)" 2>/dev/null || true
    # Everything but the lock, which a run starting right now may already be waiting on.
    find "$UPSTREAM_PROXY_DIR" -mindepth 1 ! -name lock -delete || true
  fi
  exec {fd}>&-
}

exec {UPSTREAM_PROXY_LOCK_FD}>"$UPSTREAM_PROXY_DIR/lock"
flock "$UPSTREAM_PROXY_LOCK_FD"
upstream_proxy_prune
UPSTREAM_PROXY_PID=$(cat "$UPSTREAM_PROXY_PID_FILE" 2>/dev/null || true)
if [ -n "$UPSTREAM_PROXY_PID" ] && kill -0 "$UPSTREAM_PROXY_PID" 2>/dev/null; then
  echo "♻️  upstream-proxy: sharing the proxy of this project's other running sandbox(es)"
else
  mkdir -p -m 755 "$UPSTREAM_PROXY_SOCK_DIR"
  UPSTREAM_PROXY_ARGS=()
  if [ "$UPSTREAM_PROXY_HOST_NETWORK" = 1 ]; then
    mkdir -p -m 755 "$UPSTREAM_PROXY_ATTEST_DIR"
    UPSTREAM_PROXY_ARGS=(--attest-dir "$UPSTREAM_PROXY_ATTEST_DIR")
  fi
  # proxy.py takes a file; keep the routes out of the process table.
  printf '%s' "$UPSTREAM_PROXY_ROUTES_JSON" >"$UPSTREAM_PROXY_ROUTE_FILE"
  "$PLUGIN_DIR/host/proxy.py" \
    ${UPSTREAM_PROXY_ENV_ARGS[@]+"${UPSTREAM_PROXY_ENV_ARGS[@]}"} \
    ${UPSTREAM_PROXY_ARGS[@]+"${UPSTREAM_PROXY_ARGS[@]}"} \
    "$UPSTREAM_PROXY_ROUTE_FILE" "$UPSTREAM_PROXY_SOCK_DIR" \
    </dev/null >"$UPSTREAM_PROXY_LOG" 2>&1 {UPSTREAM_PROXY_LOCK_FD}>&- &
  UPSTREAM_PROXY_PID=$!
  echo "$UPSTREAM_PROXY_PID" >"$UPSTREAM_PROXY_PID_FILE"
fi
mkdir -p -m 700 "$UPSTREAM_PROXY_USERS"
: >"$UPSTREAM_PROXY_USERS/$$"
# run.sh's last statement is `docker run`, so the exit hooks fire once the agent's session ends.
on_exit upstream_proxy_release
flock -u "$UPSTREAM_PROXY_LOCK_FD"
exec {UPSTREAM_PROXY_LOCK_FD}>&-

# Wait for every socket (created after its route's port, if any) rather than racing the container.
for _ in $(seq 1 50); do
  missing=0
  while read -r name; do
    [ -S "$UPSTREAM_PROXY_SOCK_DIR/$name.sock" ] || missing=1
  done < <(jq -r '.[].name' "$UPSTREAM_PROXY_ROUTE_FILE")
  [ "$missing" = 0 ] && break
  kill -0 "$UPSTREAM_PROXY_PID" 2>/dev/null \
    || die "upstream-proxy: the proxy exited during startup."$'\n'"$(cat "$UPSTREAM_PROXY_LOG")"
  sleep 0.1
done
[ "${missing:-1}" = 0 ] \
  || die "upstream-proxy: sockets did not appear in $UPSTREAM_PROXY_SOCK_DIR."$'\n'"$(cat "$UPSTREAM_PROXY_LOG")"

if [ "$UPSTREAM_PROXY_HOST_NETWORK" = 1 ]; then
  pass_mount "$UPSTREAM_PROXY_ATTEST_DIR" /run/upstream-proxy-attest
  pass_value UPSTREAM_PROXY_ATTEST_DIR /run/upstream-proxy-attest
else
  pass_mount "$UPSTREAM_PROXY_SOCK_DIR" /run/upstream-proxy
fi

# name:port pairs drive the container-side forwarder in root-init.sh, and the agent's briefing.
pass_value UPSTREAM_PROXY_PORTS "$(jq -r '[.[] | "\(.name):\(.port)"] | join(" ")' "$UPSTREAM_PROXY_ROUTE_FILE")"

# Each route declares the env the agent should see: endpoints pointed at loopback, and placeholder
# credentials for SDKs that insist on one. The real values never leave this host.
#
# ${VAR} in a value is expanded from the route file's envFile, else run.sh's environment, so
# non-secret settings (a deployment name, an api version) need not be duplicated here. This DOES
# put that value in the container — naming a credential here defeats the proxy, so don't.
declare -A UPSTREAM_PROXY_ENV=()
env_scan_into UPSTREAM_PROXY_ENV "$UPSTREAM_PROXY_ENV_FILE"

upstream_proxy_expand() {
  local in=$1 out="" name rest
  while [ -n "$in" ]; do
    case "$in" in
      *'${'*)
        out+=${in%%'${'*}
        rest=${in#*'${'}
        case "$rest" in
          *'}'*)
            name=${rest%%\}*}
            out+="${UPSTREAM_PROXY_ENV[$name]-${!name-}}"
            in=${rest#*\}}
            ;;
          *) out+=$rest; in="" ;;
        esac
        ;;
      *) out+=$in; in="" ;;
    esac
  done
  printf '%s' "$out"
}

while IFS=$'\t' read -r key value; do
  pass_value "$key" "$(upstream_proxy_expand "$value")"
done < <(jq -r '.[] | (.containerEnv // {}) | to_entries[] | "\(.key)\t\(.value)"' "$UPSTREAM_PROXY_ROUTE_FILE")

echo "🔒 upstream-proxy: $(jq -r '[.[].name] | join(", ")' "$UPSTREAM_PROXY_ROUTE_FILE") proxied from the host"
