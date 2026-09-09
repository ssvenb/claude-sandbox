# shellcheck shell=sh
# Agent stage: provision /workspace and the per-run branch. Needs the git-credentials capability
# (see plugin.json) so the clone and the pushes authenticate.

# A fresh, isolated clone — no bind-mount to the host checkout.
BASE_BRANCH="${BASE_BRANCH:-main}"
git clone "$REPO_URL" /workspace
cd /workspace


# Prefix and commit identity come from the running agent's manifest, so a copilot run is not signed
# as Claude Code. An explicit BRANCH_PREFIX names the identity of this run instead: work from a
# `feature-x` prefix should not show up authored as "Claude Code".
if [ -n "${BRANCH_PREFIX:-}" ]; then
  agent_git_name="$BRANCH_PREFIX"
  agent_git_email="$BRANCH_PREFIX@sandbox.local"
else
  BRANCH_PREFIX=$(agent_meta '.git.branchPrefix // empty')
  BRANCH_PREFIX="${BRANCH_PREFIX:-$AGENT}"
  agent_git_name=$(agent_meta '.git.userName // empty')
  agent_git_email=$(agent_meta '.git.userEmail // empty')
fi
git config user.name "${agent_git_name:-$AGENT}"
git config user.email "${agent_git_email:-$AGENT@sandbox.local}"

# Each run gets its own branch so parallel agents don't collide: the date makes a branch listing
# readable, the RUN_ID keeps it unique.
AGENT_BRANCH_PREFIX="$BRANCH_PREFIX"
AGENT_BRANCH="$AGENT_BRANCH_PREFIX/$RUN_DATE-$RUN_ID"
export RUN_ID AGENT_BRANCH AGENT_BRANCH_PREFIX

if [ "${RESUME:-0}" = 1 ]; then
  # The branch's date segment is the day the run was created, not today, so look it up by its
  # RUN_ID suffix among the branches the clone already fetched; the computed name is the fallback.
  resumed=$(git for-each-ref --format='%(refname:strip=3)' "refs/remotes/origin/*/*-$RUN_ID" |
              head -n 1)
  [ -n "$resumed" ] && AGENT_BRANCH="$resumed"
  export AGENT_BRANCH
  git fetch origin "$AGENT_BRANCH" || true
  git checkout "$AGENT_BRANCH"
  echo "✅ Resumed branch $AGENT_BRANCH in isolated /workspace (RUN_ID=$RUN_ID)"

  printf 'You are resuming an existing sandbox run (RUN_ID=%s) on its existing branch %s.' \
    "$RUN_ID" "$AGENT_BRANCH" >> "$AGENT_PROMPT_FILE"

  # Surface any existing PR so the agent pushes to it instead of opening a duplicate.
  pr=$(gh pr view "$AGENT_BRANCH" --json number,url,state \
         --jq 'select(.state=="OPEN") | "#\(.number) \(.url)"' 2>/dev/null || true)
  [ -n "$pr" ] && printf ' A pull request already exists for this branch (%s); push follow-up work to this branch and do NOT open a new PR.' \
    "$pr" >> "$AGENT_PROMPT_FILE"

else
  # Created HERE, before the agent starts, so the branch guard applies to all of its work.
  git checkout -b "$AGENT_BRANCH" "origin/$BASE_BRANCH"
  echo "✅ Created branch $AGENT_BRANCH off origin/$BASE_BRANCH in isolated /workspace (RUN_ID=$RUN_ID)"

  # stdout is invisible to the agent, so the branch has to reach it through the prompt — otherwise
  # its first act is often to create one of its own, which the guard then rejects.
  printf 'You are working in an isolated clone at /workspace on the branch %s, created for this sandbox run (RUN_ID=%s) off %s. Commit and push your work to this branch.' \
    "$AGENT_BRANCH" "$RUN_ID" "$BASE_BRANCH" >> "$AGENT_PROMPT_FILE"
fi

# Only claimed when the guard is actually enforcing it: describing a restriction that isn't there
# would just make the agent waste turns working around it.
case " ${ENABLED_PLUGINS:-} " in
  *" branch-guard "*)
    printf ' You cannot leave this branch: a PreToolUse hook blocks every `git checkout`, `git switch`, `git branch` and `git worktree` command outright, and allows pushes only to %s. Do not attempt to switch or create a branch, and use `git restore` rather than `git checkout` to discard changes to a file.\n' \
      "$AGENT_BRANCH" >> "$AGENT_PROMPT_FILE" ;;
  *)
    printf ' Stay on this branch for all of your work.\n' >> "$AGENT_PROMPT_FILE" ;;
esac
