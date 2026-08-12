# shellcheck shell=sh
# Launch stage (runs as 'node', last thing the boot sequence does). --allow-all approves every
# tool, path and URL up front (the sandbox is the boundary, not the prompts) and marks the
# working directory trusted; -i starts an interactive session that runs the briefing first.
# $AGENT_LAUNCH_CMD is unquoted on purpose so a plugin-supplied wrapper splits into words.
# shellcheck disable=SC2086
if [ -n "$AGENT_PROMPT" ]; then
  ${AGENT_LAUNCH_CMD:-copilot} --allow-all -i "$AGENT_PROMPT"
else
  ${AGENT_LAUNCH_CMD:-copilot} --allow-all
fi
