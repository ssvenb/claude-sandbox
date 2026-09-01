# shellcheck shell=sh
# Launch stage (runs as 'node', last thing the boot sequence does). A plugin may have replaced
# $AGENT_LAUNCH_CMD with a wrapper (e.g. the headroom proxy), everything up to and including the
# point where Claude's own flags begin; unquoted on purpose so it splits into words.
#
# Effort level: the sandbox runs unattended and mostly on mechanical work, so it defaults to the
# cheapest setting rather than inheriting whatever the interactive default is. $CLAUDE_EFFORT
# (low, medium, high, xhigh, max) overrides it per run.
# shellcheck disable=SC2086
if [ -n "$AGENT_PROMPT" ]; then
  ${AGENT_LAUNCH_CMD:-claude} --dangerously-skip-permissions --effort "${CLAUDE_EFFORT:-low}" "$AGENT_PROMPT"
else
  ${AGENT_LAUNCH_CMD:-claude} --dangerously-skip-permissions --effort "${CLAUDE_EFFORT:-low}"
fi
