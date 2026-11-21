# shellcheck shell=bash
# Host stage: the repo coordinates the agent stage needs, read from the checkout run.sh was started
# in — the folder open on the host is the repo the agent works on.

# A project whose repo is a git URL has no checkout here (HOST_CWD is empty): the URL is REPO_URL
# already, and BASE_BRANCH, unless set, is the clone's own default branch, read in the container.
if [ -z "$HOST_CWD" ]; then
  [ -n "${REPO_URL:-}" ] || die "git-workspace: no checkout on this machine and no REPO_URL to clone"
  pass_value REPO_URL "$REPO_URL"
  [ -z "${BASE_BRANCH:-}" ] || pass_value BASE_BRANCH "$BASE_BRANCH"
else
  git -C "$HOST_CWD" rev-parse --git-dir >/dev/null 2>&1 ||
    die "git-workspace: $HOST_CWD is not a git repository (set the project's \"repo\" to one)"

  REPO_URL=$(git -C "$HOST_CWD" remote get-url origin 2>/dev/null) ||
    die "git-workspace: $HOST_CWD has no 'origin' remote to clone from"
  [ -n "$REPO_URL" ] || die "git-workspace: the 'origin' remote of $HOST_CWD has an empty URL"

  pass_value REPO_URL "$REPO_URL"

  # Not every repo calls its default branch "main": ask origin/HEAD, then the remote, then guess.
  # Getting it wrong otherwise surfaces in the container as "'origin/main' is not a commit", long
  # after the cheap check was possible.
  if [ -z "${BASE_BRANCH:-}" ]; then
    BASE_BRANCH=$(git -C "$HOST_CWD" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null) &&
      BASE_BRANCH=${BASE_BRANCH#origin/}
    [ -n "$BASE_BRANCH" ] ||
      BASE_BRANCH=$(git -C "$HOST_CWD" remote show origin 2>/dev/null |
        sed -n 's/.*HEAD branch: //p')
    [ -n "$BASE_BRANCH" ] || BASE_BRANCH=main
  fi

  git -C "$HOST_CWD" rev-parse --verify --quiet "refs/remotes/origin/$BASE_BRANCH" >/dev/null ||
    die "git-workspace: origin has no branch '$BASE_BRANCH' to cut from (set BASE_BRANCH in the project's file, or run 'git fetch origin')"

  pass_value BASE_BRANCH "$BASE_BRANCH"
fi

# The branch name's leading segment belongs to the repo being worked on, so it is read from there:
# the project's file first, then the environment. With neither the agent stage falls back
# to the agent manifest's branchPrefix, then the agent's directory name.
BRANCH_PREFIX=$(plugin_config '.branchPrefix' "${BRANCH_PREFIX:-}")
if [ -n "$BRANCH_PREFIX" ]; then
  pass_value BRANCH_PREFIX "$BRANCH_PREFIX"
fi
