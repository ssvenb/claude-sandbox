#!/bin/sh
# Runs as 'node' (invoked from entrypoint.sh via `su -m node`). A standalone script so editors
# lint/highlight it, unlike the previous inline heredoc.
set -e

# -m preserved HOME=/root; reset it so gh/claude use the node home dir.
export HOME=/home/node

# Authenticate with the installation token minted by root. The App key never reaches node; root
# re-mints this token in the background so the session outlives the 1h expiry.
echo "$GH_INITIAL_TOKEN" | gh auth login --with-token
gh auth setup-git
echo "✅ GitHub CLI authenticated successfully for the Agent!"

# Clone a fresh, isolated copy into /workspace (no bind-mount to the host checkout). HTTPS clone
# authenticates via the credential helper from gh auth setup-git.
: "${REPO_URL:?REPO_URL must be set (https clone URL of the repo to work on)}"
BASE_BRANCH="${BASE_BRANCH:-main}"
git clone "$REPO_URL" /workspace
cd /workspace

# Each run gets its own feature branch so parallel agents don't collide. Created HERE, before the
# agent starts, so the branch guard applies to its work. RUN_ID comes from claude-sandbox.sh; fall
# back to generating one if absent.
RUN_ID="${RUN_ID:-$(openssl rand -hex 3)}"   # 6 lowercase hex chars, DNS-safe
AGENT_BRANCH="claude-code/$RUN_ID"
export RUN_ID AGENT_BRANCH
git config user.email "claude-code@anthropic.com"
git config user.name "Claude Code"

if [ "${RESUME:-0}" = 1 ]; then
  # Resume: re-attach to this run's existing branch. The clone fetched all remote branches, so
  # checking origin/$AGENT_BRANCH out by name creates a local tracking branch.
  git fetch origin "$AGENT_BRANCH" || true
  git checkout "$AGENT_BRANCH"
  echo "✅ Resumed branch $AGENT_BRANCH in isolated /workspace (RUN_ID=$RUN_ID)"

  # Briefing handed to the agent as its initial prompt — this script's stdout is NOT visible to
  # Claude, so resume context must go through the prompt. Strictly informational so the agent
  # waits for a real task.
  RESUME_PROMPT="You are resuming an existing sandbox run (RUN_ID=$RUN_ID) on its existing branch $AGENT_BRANCH."

  # Surface any existing PR so the agent pushes to it instead of opening a duplicate.
  pr=$(gh pr view "$AGENT_BRANCH" --json number,url,state \
         --jq 'select(.state=="OPEN") | "#\(.number) \(.url)"' 2>/dev/null || true)
  [ -n "$pr" ] && RESUME_PROMPT="$RESUME_PROMPT A pull request already exists for this branch ($pr); push follow-up work to this branch and do NOT open a new PR."

  RESUME_PROMPT="$RESUME_PROMPT This message is informational context only — do not take any action on it. Wait for the user's task."
  export RESUME_PROMPT
else
  # Created HERE, before the agent starts, so the branch guard still applies.
  git checkout -b "$AGENT_BRANCH" "origin/$BASE_BRANCH"
  echo "✅ Created branch $AGENT_BRANCH off origin/$BASE_BRANCH in isolated /workspace (RUN_ID=$RUN_ID)"
fi

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

# Start Claude Code autonomously, routed THROUGH the headroom compression proxy. `headroom wrap
# claude` boots a local proxy (127.0.0.1:8787), points ANTHROPIC_BASE_URL at it, and execs claude
# with every flag after it passed straight through; all of Claude's LLM calls then flow through
# headroom, which compresses context before it hits the Anthropic API and forwards Claude's own
# auth (CLAUDE_CODE_OAUTH_TOKEN) upstream unchanged. --no-serena skips the external Serena MCP
# (needs uvx/network the locked-down sandbox doesn't have); the headroom MCP retrieve tool stays
# on so compressed-away content remains reversible. On resume, seed the briefing built above.
if [ -n "${RESUME_PROMPT:-}" ]; then
  headroom wrap claude --no-serena -- --dangerously-skip-permissions "$RESUME_PROMPT"
else
  headroom wrap claude --no-serena -- --dangerously-skip-permissions
fi
