#!/bin/sh
# Runs as 'node' (invoked from entrypoint.sh via `su -m node`). A standalone script so editors
# lint/highlight it, unlike the previous inline heredoc.
set -e

# -m preserved HOME=/root; reset it so gh/claude use the node home dir.
export HOME=/home/node

# shellcheck source=lib/plugins.sh
. /usr/local/lib/sandbox/plugins.sh

# Plugins append briefing lines here (e.g. "you are resuming branch X"); the joined text becomes
# Claude's initial prompt. This script's stdout is NOT visible to the agent, so context that
# must reach it has to travel through the prompt.
AGENT_PROMPT_FILE=$(mktemp)
export AGENT_PROMPT_FILE

# Agent stage: authenticate, provision /workspace, set up guardrails. With every plugin off,
# /workspace is simply an empty directory the agent starts from scratch in.
plugin_run_stage agent-init

cd /workspace

# Pre-seed Claude config so the agent boots non-interactively: skip onboarding, accept the
# --dangerously-skip-permissions warning, and trust /workspace.
CONFIG="$HOME/.claude.json"
[ -f "$CONFIG" ] || echo "{}" > "$CONFIG"
tmp=$(mktemp)
jq ".hasCompletedOnboarding = true
    | .theme = (.theme // \"dark\")
    | .bypassPermissionsModeAccepted = true
    | .projects[\"/workspace\"].hasTrustDialogAccepted = true" \
   "$CONFIG" > "$tmp" && mv "$tmp" "$CONFIG"

AGENT_PROMPT=$(cat "$AGENT_PROMPT_FILE")
rm -f "$AGENT_PROMPT_FILE"

# Start Claude Code autonomously, routed THROUGH the headroom compression proxy. `headroom wrap
# claude` boots a local proxy (127.0.0.1:8787), points ANTHROPIC_BASE_URL at it, and execs claude
# with every flag after it passed straight through; all of Claude's LLM calls then flow through
# headroom, which compresses context before it hits the Anthropic API and forwards Claude's own
# auth (CLAUDE_CODE_OAUTH_TOKEN) upstream unchanged. --no-serena skips the external Serena MCP
# (needs uvx/network the locked-down sandbox doesn't have); the headroom MCP retrieve tool stays
# on so compressed-away content remains reversible.
if [ -n "$AGENT_PROMPT" ]; then
  headroom wrap claude --no-serena -- --dangerously-skip-permissions "$AGENT_PROMPT"
else
  headroom wrap claude --no-serena -- --dangerously-skip-permissions
fi

