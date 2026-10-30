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
