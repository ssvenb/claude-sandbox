# shellcheck shell=sh
# Agent stage: /workspace is already populated by the host bind-mount, so there is nothing to
# provision — just tell the agent that its edits are live on the host.

printf 'Your /workspace is a live bind-mount of a directory on the host: every edit takes effect immediately outside the sandbox and there is no per-run branch isolating your work. This message is informational context only — do not take any action on it. Wait for the user'"'"'s task.\n' \
  >> "$AGENT_PROMPT_FILE"

echo "✅ /workspace is bind-mounted from the host"
