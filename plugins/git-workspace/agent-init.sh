# shellcheck shell=sh
# Agent stage: provision /workspace and the per-run branch. Needs the git-credentials
# capability (see plugin.json) for the clone and push to authenticate.

# Clone a fresh, isolated copy into /workspace (no bind-mount to the host checkout). HTTPS clone
# authenticates via the credential helper an auth plugin installed.
BASE_BRANCH="${BASE_BRANCH:-main}"
git clone "$REPO_URL" /workspace
cd /workspace

# Each run gets its own feature branch so parallel agents don't collide. Created HERE, before the
# agent starts, so the branch guard applies to its work. RUN_ID comes from run.sh; fall back to
# generating one if absent.
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

  # Briefing for the agent's initial prompt. Strictly informational so it waits for a real task.
  printf 'You are resuming an existing sandbox run (RUN_ID=%s) on its existing branch %s.' \
    "$RUN_ID" "$AGENT_BRANCH" >> "$AGENT_PROMPT_FILE"

  # Surface any existing PR so the agent pushes to it instead of opening a duplicate.
  pr=$(gh pr view "$AGENT_BRANCH" --json number,url,state \
         --jq 'select(.state=="OPEN") | "#\(.number) \(.url)"' 2>/dev/null || true)
  [ -n "$pr" ] && printf ' A pull request already exists for this branch (%s); push follow-up work to this branch and do NOT open a new PR.' \
    "$pr" >> "$AGENT_PROMPT_FILE"

  printf ' This message is informational context only — do not take any action on it. Wait for the user'"'"'s task.\n' \
    >> "$AGENT_PROMPT_FILE"
else
  # Created HERE, before the agent starts, so the branch guard still applies.
  git checkout -b "$AGENT_BRANCH" "origin/$BASE_BRANCH"
  echo "✅ Created branch $AGENT_BRANCH off origin/$BASE_BRANCH in isolated /workspace (RUN_ID=$RUN_ID)"
fi
