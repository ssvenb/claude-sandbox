# shellcheck shell=sh
# Launch stage (runs as 'node', last thing the boot sequence does). $AGENT_LAUNCH_CMD may have
# been replaced by a plugin with a wrapper; unquoted on purpose so it
# splits into words. The effort level
# defaults to medium. The briefing goes into the system prompt rather than a first
# message, so it costs no turn, stays out of the transcript and survives /clear.
# shellcheck disable=SC2086
${AGENT_LAUNCH_CMD:-claude} --dangerously-skip-permissions \
  --effort "${CLAUDE_EFFORT:-medium}" ${AGENT_PROMPT:+--append-system-prompt "$AGENT_PROMPT"}
