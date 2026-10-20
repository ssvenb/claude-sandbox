# shellcheck shell=sh
# Root stage. Bridge each bind-mounted unix socket to a loopback TCP port so ordinary HTTP clients
# can reach it. No secret here — the credential lives in the host proxy on the far side — but the
# forwarder runs as root so `node` cannot replace it and point an endpoint somewhere else, and it
# only serves this container's own processes (see root/forward.py).
#
# Under host-network the loopback is the host's, shared with every other sandbox, and the project's
# host proxy listens on the ports itself; this container only vouches for its own processes'
# connections, so its sibling sandboxes keep the ports when it exits.

# Logged, not inherited: the agent's TUI owns the terminal, and a stray connection error written to
# it would scribble over the screen. A socket or port that cannot be bound fails the start (set -e).
if [ -n "${UPSTREAM_PROXY_ATTEST_DIR:-}" ]; then
  "$PLUGIN_DIR/root/forward.py" --log /var/log/upstream-proxy.log --attest "$UPSTREAM_PROXY_ATTEST_DIR"
  for entry in ${UPSTREAM_PROXY_PORTS:-}; do
    echo "🔌 upstream-proxy: 127.0.0.1:${entry##*:} → ${entry%%:*} (host network)"
  done
  unset entry
  return 0
fi

_routes=""
for entry in ${UPSTREAM_PROXY_PORTS:-}; do
  name=${entry%%:*}
  port=${entry##*:}
  sock="/run/upstream-proxy/$name.sock"
  if [ ! -S "$sock" ]; then
    echo "⚠️  upstream-proxy: $sock is missing, skipping $name" >&2
    continue
  fi
  _routes="$_routes $port=$sock"
  echo "🔌 upstream-proxy: 127.0.0.1:$port → $name"
done

if [ -n "$_routes" ]; then
  # shellcheck disable=SC2086  # one PORT=SOCKET argument per route
  "$PLUGIN_DIR/root/forward.py" --log /var/log/upstream-proxy.log $_routes
fi
unset _routes entry name port sock
