# shellcheck shell=sh
# Agent stage: run the project's setup commands (`npm ci`, `make bootstrap`, `uv sync`, …) as the
# agent user, in /workspace. Priority 25 puts this after the workspace plugins (20) have
# provisioned the checkout and before the guardrails (30) and the launcher (40).
#
# These are arbitrary shell from the project config, so they deliberately run HERE: unprivileged,
# with the secrets already dropped, and with exactly the environment the agent itself will have —
# which also means a command that succeeds here works the same way when the agent repeats it.

# Sourced, not executed, so nothing here may exit: a failure must leave the boot sequence intact.
if [ -n "${PROJECT_DEPS_SETUP:-}" ] && cd /workspace; then
  # One command per line: the host validated the list as JSON strings, and jq -r gives each back
  # verbatim. A failure is reported and the boot continues — a half-provisioned workspace the
  # agent knows about beats no agent at all.
  printf '%s' "$PROJECT_DEPS_SETUP" | jq -r '.[]' | while IFS= read -r _cmd; do
    [ -n "$_cmd" ] || continue
    echo "🔧 project-deps: $_cmd"
    sh -c "$_cmd" || echo "⚠️  project-deps: setup command failed: $_cmd" >&2
  done

  # Tell the agent what boot already did, so it doesn't spend a turn re-running it.
  _deps_list=$(printf '%s' "$PROJECT_DEPS_SETUP" | jq -r 'join("; ")')
  printf 'Project setup commands were already run for you in /workspace during boot (%s); do not repeat them unless something is missing. This message is informational context only — do not take any action on it. Wait for the user'"'"'s task.\n' \
    "$_deps_list" >> "$AGENT_PROMPT_FILE"
  unset _cmd _deps_list
fi
