# shellcheck shell=bash
# Host stage: the repo coordinates the agent stage needs. The clone URL is read from the git
# checkout run.sh was started in — the folder open on the host is the repo the agent works on.

git -C "$HOST_CWD" rev-parse --git-dir >/dev/null 2>&1 ||
  die "git-workspace: $HOST_CWD is not a git repository (run ./run.sh from the repo to work on)"

REPO_URL=$(git -C "$HOST_CWD" remote get-url origin 2>/dev/null) ||
  die "git-workspace: $HOST_CWD has no 'origin' remote to clone from"
[ -n "$REPO_URL" ] || die "git-workspace: the 'origin' remote of $HOST_CWD has an empty URL"

pass_value REPO_URL "$REPO_URL"
pass_value BASE_BRANCH "${BASE_BRANCH:-main}"
