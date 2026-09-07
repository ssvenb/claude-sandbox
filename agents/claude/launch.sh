# shellcheck shell=sh
# Launch stage (runs as 'node', last thing the boot sequence does). $AGENT_LAUNCH_CMD may have
# been replaced by a plugin with a wrapper (e.g. the headroom proxy); unquoted on purpose so it
# splits into words. The sandbox runs unattended on mostly mechanical work, so the effort level
# defaults to the cheapest setting.
# shellcheck disable=SC2086
${AGENT_LAUNCH_CMD:-claude} --dangerously-skip-permissions \
  --effort "${CLAUDE_EFFORT:-low}" ${AGENT_PROMPT:+"$AGENT_PROMPT"}
