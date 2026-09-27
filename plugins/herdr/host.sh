# shellcheck shell=bash
# Host stage: herdr identifies an agent pane by its foreground process, which for a sandbox is
# `docker` — the agent itself lives in another PID namespace herdr cannot see. herdr's documented
# escape hatch for wrappers is HERDR_AGENT=<agent> on the wrapper process: it then applies that
# agent's screen manifest to the pane's output, which docker passes through unchanged. This file is
# sourced into run.sh, so the export reaches `docker run`. Nothing enters the container.
#
# Only meaningful inside a herdr pane (HERDR_ENV=1); anywhere else this does nothing. The agent
# directory names used here (claude, copilot) match herdr's own agent ids.

if [ "${HERDR_ENV:-}" = "1" ]; then
  export HERDR_AGENT="$AGENT"
fi
