# shellcheck shell=sh
# Launch stage (runs as 'node', last thing the boot sequence does). --allow-all approves every
# tool, path and URL up front — the sandbox is the boundary, not the prompts — and marks the
# working directory trusted; -i starts an interactive session that runs the briefing first.
# The briefing arrives as a message, so it is qualified as context rather than a task.
# $AGENT_LAUNCH_CMD is unquoted on purpose so a plugin-supplied wrapper splits into words.
#
# Every run's session is named after its RUN_ID, so `run.sh --resume` picks the same session back
# up. It only outlives the container when ~/.copilot is mounted (copilot-home).
#
# $AGENT_TASK (run.sh --task) is the user's task: it closes that first message, which then asks
# for it to be done instead of for a wait.
# A web chat (run.sh --chat) has no terminal: the agent runs behind its chat bridge, which drives
# it through the GitHub Copilot SDK and resumes the same conversation.
if [ "${AGENT_UI:-}" = chat ]; then
  exec node "$AGENT_DIR/chat.mjs"
fi
session="sandbox-${RUN_ID:?}"
if [ -n "$AGENT_TASK" ]; then
  AGENT_PROMPT="${AGENT_PROMPT:+$AGENT_PROMPT

}The user's task:
$AGENT_TASK"
elif [ -n "$AGENT_PROMPT" ]; then
  AGENT_PROMPT="$AGENT_PROMPT
This message is informational context only — do not take any action on it. Wait for the user's task."
fi
if [ "${RESUME:-0}" = 1 ]; then
  started=$(date +%s)
  # shellcheck disable=SC2086
  ${AGENT_LAUNCH_CMD:-copilot} --allow-all --resume="$session" ${AGENT_PROMPT:+-i "$AGENT_PROMPT"} && exit 0
  status=$?
  # No session by that name: the CLI refuses at once with status 2. Anything else is the end of
  # a resumed session and stays its result.
  [ "$status" = 2 ] && [ $(($(date +%s) - started)) -lt 5 ] || exit "$status"
  echo "No saved Copilot session for this run; starting a new one."
fi
# shellcheck disable=SC2086
${AGENT_LAUNCH_CMD:-copilot} --allow-all --name="$session" ${AGENT_PROMPT:+-i "$AGENT_PROMPT"}
