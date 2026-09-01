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

# Everything the plugins wrote is boot-time context — the branch, the setup that already ran —
# never a task. Say so once, here, instead of in every plugin that briefs the agent, so the agent
# doesn't treat its own provisioning as an instruction. Only when there is something to qualify:
# with no plugin briefing, the agent starts with an empty prompt and no preamble at all.
if [ -s "$AGENT_PROMPT_FILE" ]; then
  printf 'This message is informational context only — do not take any action on it. Wait for the user'"'"'s task.\n' \
    >> "$AGENT_PROMPT_FILE"
fi

AGENT_PROMPT=$(cat "$AGENT_PROMPT_FILE")
export AGENT_PROMPT
rm -f "$AGENT_PROMPT_FILE"

# Hand over to the agent. Its launch.sh turns $AGENT_PROMPT into the right flags and honours
# $AGENT_LAUNCH_CMD, which a plugin may have replaced with a wrapper (e.g. the headroom proxy).
agent_run_stage launch

