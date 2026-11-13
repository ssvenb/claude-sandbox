#!/bin/sh
# Runs as 'node' (invoked from entrypoint.sh via `setpriv`).
set -e

# -m preserved HOME=/root; reset it so gh/claude use the node home dir.
export HOME=/home/node

# shellcheck source=lib/plugins.sh
. /usr/local/lib/sandbox/plugins.sh
# shellcheck source=lib/agents.sh
. /usr/local/lib/sandbox/agents.sh

# Plugins append briefing lines here; the joined text is handed to the agent's launch.sh. This
# script's stdout is NOT visible to the agent, so context that must reach it travels this way.
AGENT_PROMPT_FILE=$(mktemp)
export AGENT_PROMPT_FILE

# What becomes of the ports it serves on (src/lib/host-ports.sh): the agent would otherwise assume
# a shared network, or spend a turn wondering how the user reaches its server.
if [ -d /run/ports ]; then
  {
    printf '## Ports\n\n'
    printf 'This container has a network of its own. The project publishes these TCP ports: %s. ' \
      "$(printf '%s' "${PORTS:-}" | sed 's/ /, /g')"
    printf 'Whatever a process of yours listens on one of them (on any address, 127.0.0.1 '
    printf 'included) reaches the user within a second or two, through a proxy on their machine, '
    printf 'and shows as a button on your session in their dashboard; any other port stays inside '
    printf 'this container, so serve what the user should see on one of those. There it gets the '
    printf 'same port number while that is free, otherwise another one, since other sessions may '
    printf 'serve on the same port: do not assume the number the user sees. Services the host '
    printf 'machine offers on a non-loopback address are at host.docker.internal; its localhost is '
    printf 'not reachable from here.\n'
  } >>"$AGENT_PROMPT_FILE"
fi

# The agent seeds its own config first, then the plugins authenticate, provision /workspace and
# set up guardrails. With every plugin off, /workspace is simply an empty directory.
agent_run_stage agent-init
plugin_run_stage agent-init

cd /workspace

AGENT_PROMPT=$(cat "$AGENT_PROMPT_FILE")
export AGENT_PROMPT
rm -f "$AGENT_PROMPT_FILE"

# launch.sh turns $AGENT_PROMPT into the right flags and honours $AGENT_LAUNCH_CMD, which a plugin
# may have replaced with a wrapper.
agent_run_stage launch
