# shellcheck shell=sh
# Launch stage (runs as 'node', last thing the boot sequence does). --allow-all approves every
# tool, path and URL up front — the sandbox is the boundary, not the prompts — and marks the
# working directory trusted; -i starts an interactive session that runs the briefing first.
# The briefing arrives as a message, so it is qualified as context rather than a task.
# $AGENT_LAUNCH_CMD is unquoted on purpose so a plugin-supplied wrapper splits into words.
if [ -n "$AGENT_PROMPT" ]; then
  AGENT_PROMPT="$AGENT_PROMPT
This message is informational context only — do not take any action on it. Wait for the user's task."
fi
# shellcheck disable=SC2086
${AGENT_LAUNCH_CMD:-copilot} --allow-all ${AGENT_PROMPT:+-i "$AGENT_PROMPT"}
