# shellcheck shell=sh
# Launch stage (runs as 'node', last thing the boot sequence does). A plugin may have replaced
# $AGENT_LAUNCH_CMD with a wrapper (e.g. the headroom proxy), everything up to and including the
# point where Claude's own flags begin; unquoted on purpose so it splits into words.
# shellcheck disable=SC2086
if [ -n "$AGENT_PROMPT" ]; then
  ${AGENT_LAUNCH_CMD:-claude} --dangerously-skip-permissions "$AGENT_PROMPT"
else
  ${AGENT_LAUNCH_CMD:-claude} --dangerously-skip-permissions
fi
