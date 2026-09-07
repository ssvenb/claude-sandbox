# shellcheck shell=sh
# Agent stage. Tell the agent what it has, and — just as important — what it does not have, so it
# does not waste a turn hunting for an API key that was deliberately left on the host.

[ -n "${UPSTREAM_PROXY_PORTS:-}" ] || return 0

{
  echo
  echo "## Proxied upstreams"
  echo
  echo "Some APIs are reached through a credential-injecting proxy running outside this container:"
  echo
  for entry in $UPSTREAM_PROXY_PORTS; do
    echo "- \`${entry%%:*}\` at http://127.0.0.1:${entry##*:}"
  done
  echo
  echo "The proxy adds the real credentials to every request, so the environment holds only"
  echo "placeholder keys — do not try to find, reconstruct, or replace them, and do not bypass the"
  echo "proxy by calling the upstream directly. The 127.0.0.1 addresses above are the real"
  echo "endpoints as far as this container is concerned: the proxy swaps them for the actual"
  echo "upstream hostnames on the way out and swaps them back in every response, so treat them as"
  echo "the canonical URLs and write them into code and config as-is. The proxy relays only an"
  echo "allowlisted set of methods"
  echo "and paths; anything else comes back as a 403 from the sandbox, not from the upstream."
} >> "$AGENT_PROMPT_FILE"
