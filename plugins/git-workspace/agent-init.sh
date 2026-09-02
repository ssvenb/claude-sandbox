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
# Branch prefix and commit identity come from the running agent's manifest ("git" block in
# agents/<name>/agent.json), so a copilot run is not signed as Claude Code. An agent that omits
# the block falls back to its own directory name; BRANCH_PREFIX in .env overrides both.
if [ -z "${BRANCH_PREFIX:-}" ]; then
  BRANCH_PREFIX=$(agent_meta '.git.branchPrefix // empty')
  BRANCH_PREFIX="${BRANCH_PREFIX:-$AGENT}"
fi
AGENT_BRANCH_PREFIX="$BRANCH_PREFIX"
# The date makes a branch listing readable at a glance; the RUN_ID keeps it unique.
AGENT_BRANCH="$AGENT_BRANCH_PREFIX/$(date -u +%Y%m%d)-$RUN_ID"
export RUN_ID AGENT_BRANCH AGENT_BRANCH_PREFIX
agent_git_name=$(agent_meta '.git.userName // empty')
agent_git_email=$(agent_meta '.git.userEmail // empty')
git config user.name "${agent_git_name:-$AGENT}"
git config user.email "${agent_git_email:-$AGENT@sandbox.local}"

if [ "${RESUME:-0}" = 1 ]; then
  # Resume: re-attach to this run's existing branch. Its date segment is the day the run was
  # created, not today, so the branch is looked up by its RUN_ID suffix among the remote branches
  # the clone already fetched; the computed name is only the fallback.
  resumed=$(git for-each-ref --format='%(refname:strip=3)' "refs/remotes/origin/*/*-$RUN_ID" |
              head -n 1)
  [ -n "$resumed" ] && AGENT_BRANCH="$resumed"
  export AGENT_BRANCH
  # The clone fetched all remote branches, so checking origin/$AGENT_BRANCH out by name creates a
  # local tracking branch.
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

else
  # Created HERE, before the agent starts, so the branch guard still applies.
  git checkout -b "$AGENT_BRANCH" "origin/$BASE_BRANCH"
  echo "✅ Created branch $AGENT_BRANCH off origin/$BASE_BRANCH in isolated /workspace (RUN_ID=$RUN_ID)"

  # Same briefing role as the resume path: stdout is invisible to the agent, so the branch it is
  # on has to reach it through the prompt — otherwise its first act is often to create one of its
  # own, which the guard then rejects.
  printf 'You are working in an isolated clone at /workspace on the branch %s, created for this sandbox run (RUN_ID=%s) off %s. Commit and push your work to this branch.' \
    "$AGENT_BRANCH" "$RUN_ID" "$BASE_BRANCH" >> "$AGENT_PROMPT_FILE"
fi

# Only claimed when the guard is actually enforcing it — the plugin is Claude-only and can be
# switched off, and telling the agent about a restriction that isn't there would be a lie it
# would waste turns working around.
case " ${ENABLED_PLUGINS:-} " in
  *" branch-guard "*)
    printf ' You cannot leave this branch: a PreToolUse hook blocks every `git checkout`, `git switch`, `git branch` and `git worktree` command outright, and allows pushes only to %s. Do not attempt to switch or create a branch, and use `git restore` rather than `git checkout` to discard changes to a file.\n' \
      "$AGENT_BRANCH" >> "$AGENT_PROMPT_FILE" ;;
  *)
    printf ' Stay on this branch for all of your work.\n' >> "$AGENT_PROMPT_FILE" ;;
esac
