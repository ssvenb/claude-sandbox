# shellcheck shell=sh
# Agent stage. Tell the agent what it has and — just as important — what it does not, so it does
# not waste a turn hunting for an API key that was deliberately left on the host.

[ -n "${UPSTREAM_PROXY_PORTS:-}" ] || return 0

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
  printf 'as the canonical URLs and write them into code and config as-is. The proxy relays only '
  printf 'an allowlisted set of methods and paths; anything else comes back as a 403 from the '
  printf 'sandbox, not from the upstream.\n'
} >> "$AGENT_PROMPT_FILE"
