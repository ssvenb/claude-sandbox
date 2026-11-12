# shellcheck shell=sh
# Launch stage (runs as 'node', last thing the boot sequence does). $AGENT_LAUNCH_CMD may have
# been replaced by a plugin with a wrapper; unquoted on purpose so it
# splits into words. The effort level
# defaults to medium. The briefing goes into the system prompt rather than a first
# message, so it costs no turn, stays out of the transcript and survives /clear.
#
# Every run's conversation gets an id derived from its RUN_ID, so `run.sh --resume` picks the
# same conversation back up. Every sandbox works in /workspace, so all their transcripts share one
# project directory and `--continue` would grab whichever run was last, not this one. The
# transcript only outlives the container when ~/.claude is mounted (claude-home); without it a
# resumed run starts a fresh conversation under the same id.
#
# $AGENT_TASK (run.sh --task) is the conversation's first message: the agent starts on it at once.
session="5a4db0c0-0000-4000-8000-000000${RUN_ID:?}"
if [ "${RESUME:-0}" = 1 ] && [ -f "$HOME/.claude/projects/-workspace/$session.jsonl" ]; then
  set -- --resume "$session"
else
  set -- --session-id "$session"
fi
# shellcheck disable=SC2086
${AGENT_LAUNCH_CMD:-claude} --dangerously-skip-permissions "$@" \
  --effort "${CLAUDE_EFFORT:-medium}" ${AGENT_PROMPT:+--append-system-prompt "$AGENT_PROMPT"} \
  ${AGENT_TASK:+"$AGENT_TASK"}
