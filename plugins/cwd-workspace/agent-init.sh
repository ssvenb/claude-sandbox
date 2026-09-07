# shellcheck shell=sh
# Agent stage: the bind-mount already populated /workspace; only the warning is left to give.

printf 'Your /workspace is a live bind-mount of a directory on the host: every edit takes effect immediately outside the sandbox and there is no per-run branch isolating your work.\n' \
  >> "$AGENT_PROMPT_FILE"

echo "✅ /workspace is bind-mounted from the host"
