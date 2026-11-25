# shellcheck shell=sh
# Agent stage: provision /workspace and the per-run branch: a clone of REPO_URL (whatever
# credentials the run has authenticate it: github-auth's, ssh-credentials', none for a public repo),
# or, for a project with no repo, an empty repository of its own with no remote.

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
# The project's own userName/userEmail settings win over both.
agent_git_name="${GIT_USER_NAME:-$agent_git_name}"
agent_git_email="${GIT_USER_EMAIL:-$agent_git_email}"

# Each run gets its own branch so parallel agents don't collide: the date makes a branch listing
# readable, the RUN_ID keeps it unique.
AGENT_BRANCH_PREFIX="$BRANCH_PREFIX"
AGENT_BRANCH="$AGENT_BRANCH_PREFIX/$RUN_DATE-$RUN_ID"
export RUN_ID AGENT_BRANCH AGENT_BRANCH_PREFIX

if [ -z "${REPO_URL:-}" ]; then
  git init -q -b "$AGENT_BRANCH" /workspace
  cd /workspace
  git config user.name "${agent_git_name:-$AGENT}"
  git config user.email "${agent_git_email:-$AGENT@sandbox.local}"
  echo "✅ Started an empty repository on branch $AGENT_BRANCH in /workspace (RUN_ID=$RUN_ID)"
  printf 'You are working in a new git repository at /workspace, with no remote, on the branch %s, created for this sandbox run (RUN_ID=%s). Commit your work to this branch.' \
    "$AGENT_BRANCH" "$RUN_ID" >> "$AGENT_PROMPT_FILE"
else
  # A fresh, isolated clone — no bind-mount to the host checkout.
  git clone "$REPO_URL" /workspace
  cd /workspace
  # Unset only for a URL repo with no BASE_BRANCH: the clone's origin/HEAD is the default branch.
  if [ -z "${BASE_BRANCH:-}" ]; then
    BASE_BRANCH=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null) || BASE_BRANCH=origin/main
    BASE_BRANCH=${BASE_BRANCH#origin/}
  fi
  git config user.name "${agent_git_name:-$AGENT}"
  git config user.email "${agent_git_email:-$AGENT@sandbox.local}"

  # The branch's date segment is the day the run was created, not today, so look it up by its
  # RUN_ID suffix among the branches the clone already fetched. A run stopped before it ever pushed
  # has none: it starts its branch afresh, as a new run would.
  resumed=
  if [ "${RESUME:-0}" = 1 ]; then
    resumed=$(git for-each-ref --format='%(refname:strip=3)' "refs/remotes/origin/*/*-$RUN_ID" |
                head -n 1)
  fi

  if [ -n "$resumed" ]; then
    AGENT_BRANCH="$resumed"
    export AGENT_BRANCH
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
    # Created HERE, before the agent starts, so all of its work is on it.
    git checkout -b "$AGENT_BRANCH" "origin/$BASE_BRANCH"
    echo "✅ Created branch $AGENT_BRANCH off origin/$BASE_BRANCH in isolated /workspace (RUN_ID=$RUN_ID)"

    # stdout is invisible to the agent, so the branch has to reach it through the prompt — otherwise
    # its first act is often to create one of its own, which the guard then rejects.
    printf 'You are working in an isolated clone at /workspace on the branch %s, created for this sandbox run (RUN_ID=%s) off %s. Commit and push your work to this branch.' \
      "$AGENT_BRANCH" "$RUN_ID" "$BASE_BRANCH" >> "$AGENT_PROMPT_FILE"
  fi
fi

# The branch guard (branchGuard): git runs bin/hooks/ for every agent, whose pre-push refuses any
# ref but this run's branch. GIT_CONFIG_* outranks the repo's own core.hooksPath; the hooks chain to
# the repo's own. Only claimed where it applies — a repo with no remote pushes nowhere — since
# describing a restriction that isn't there would make the agent waste turns working around it.
if [ "${BRANCH_GUARD:-}" = 1 ]; then
  _n=${GIT_CONFIG_COUNT:-0}
  export "GIT_CONFIG_KEY_$_n=core.hooksPath" "GIT_CONFIG_VALUE_$_n=$PLUGIN_DIR/bin/hooks"
  export GIT_CONFIG_COUNT=$((_n + 1))
  unset _n
fi
if [ "${BRANCH_GUARD:-}" = 1 ] && [ -n "${REPO_URL:-}" ]; then
  printf ' Only this branch can be pushed: a pre-push hook rejects any other ref. Push it by name (`git push origin %s`).\n' \
    "$AGENT_BRANCH" >> "$AGENT_PROMPT_FILE"
else
  printf ' Stay on this branch for all of your work.\n' >> "$AGENT_PROMPT_FILE"
fi
