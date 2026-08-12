#!/bin/sh
# Runs as 'node' (invoked from entrypoint.sh via `su -m node`). A standalone script so editors
# lint/highlight it, unlike the previous inline heredoc.
set -e

# -m preserved HOME=/root; reset it so gh/claude use the node home dir.
export HOME=/home/node

# shellcheck source=lib/plugins.sh
. /usr/local/lib/sandbox/plugins.sh
# shellcheck source=lib/agents.sh
. /usr/local/lib/sandbox/agents.sh

# Plugins append briefing lines here (e.g. "you are resuming branch X"); the joined text becomes
# the agent's initial prompt. This script's stdout is NOT visible to the agent, so context that
# must reach it has to travel through the prompt.
AGENT_PROMPT_FILE=$(mktemp)
export AGENT_PROMPT_FILE

# Agent stage: first the selected agent seeds its own config, then the plugins authenticate,
# provision /workspace and set up guardrails. With every plugin off, /workspace is simply an
# empty directory the agent starts from scratch in.
agent_run_stage agent-init
plugin_run_stage agent-init

cd /workspace

AGENT_PROMPT=$(cat "$AGENT_PROMPT_FILE")
export AGENT_PROMPT
rm -f "$AGENT_PROMPT_FILE"

# Hand over to the agent. Its launch.sh turns $AGENT_PROMPT into the right flags and honours
# $AGENT_LAUNCH_CMD, which a plugin may have replaced with a wrapper (e.g. the headroom proxy).
agent_run_stage launch

