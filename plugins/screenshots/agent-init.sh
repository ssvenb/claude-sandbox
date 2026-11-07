# shellcheck shell=sh
# Agent stage: tell the agent the user's screenshots are readable.
[ -n "${AGENT_PROMPT_FILE:-}" ] || return 0
cat >> "$AGENT_PROMPT_FILE" <<'BRIEF'

The user's screenshots are mounted read-only at /home/node/Pictures/Screenshots (newest by mtime:
`ls -t`). When the user mentions "the screenshot" or "my last screenshot", look there and read the
image file to view it.
BRIEF
