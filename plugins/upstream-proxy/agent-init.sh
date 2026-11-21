# shellcheck shell=sh
# Agent stage. Bridge each bind-mounted unix socket to a loopback TCP port so ordinary HTTP clients
# can reach it (bin/forward.py). No secret here: the credential lives in the host proxy on the far
# side, which alone decides what a route may reach.

[ -n "${UPSTREAM_PROXY_PORTS:-}" ] || return 0

# Logged, not inherited: the agent's TUI owns the terminal, and a stray connection error written to
# it would scribble over the screen. A socket or port that cannot be bound fails the start (set -e).
_routes=""
for entry in $UPSTREAM_PROXY_PORTS; do
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
  mkdir -p "$HOME/.cache"
  # shellcheck disable=SC2086  # one PORT=SOCKET argument per route
  "$PLUGIN_DIR/bin/forward.py" --log "$HOME/.cache/upstream-proxy.log" $_routes
fi
unset _routes entry name port sock

# Tell the agent what it has and — just as important — what it does not, so it does not waste a
# turn hunting for an API key that was deliberately left on the host.

{
  printf '\n## Proxied upstreams\n\n'
  printf 'Some APIs are reached through a credential-injecting proxy running outside this container:\n\n'
  for entry in $UPSTREAM_PROXY_PORTS; do
    printf -- '- `%s` at http://127.0.0.1:%s\n' "${entry%%:*}" "${entry##*:}"
  done
  printf '\nThe proxy adds the real credentials to every request, so the environment holds only '
  printf 'placeholder keys — do not try to find, reconstruct, or replace them, and do not bypass '
  printf 'the proxy by calling the upstream directly. The 127.0.0.1 addresses above are the real '
  printf 'endpoints as far as this container is concerned: the proxy swaps them for the actual '
  printf 'upstream hostnames on the way out and swaps them back in every response, so treat them '
  printf 'as the canonical URLs and write them into code and config as-is. A route may relay only '
  printf 'an allowlisted set of methods and paths; anything it refuses comes back as a 403 from the '
  printf 'sandbox, not from the upstream.\n'
} >> "$AGENT_PROMPT_FILE"
