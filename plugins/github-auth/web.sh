# shellcheck shell=bash
# Web stage: the project's open pull requests and issues, each linking to its GitHub page. Asked
# through the host's own `gh` login — yours, as the project's GH_USERNAME when it names one (gh
# keeps a token per account); the App's tokens are for the container.

git -C "$HOST_CWD" remote get-url origin >/dev/null 2>&1 || return 0
if ! command -v gh >/dev/null; then
  web_note "the gh CLI is not installed on this machine"
  return 0
fi

# The project's account, not whichever one gh has active: a host logged in to several picks per project.
gh_token=
if [ -n "${GH_USERNAME:-}" ] &&
   ! gh_token=$(gh auth token --hostname "${GH_HOST:-github.com}" --user "$GH_USERNAME" 2>/dev/null); then
  web_note "gh is not logged in as $GH_USERNAME on ${GH_HOST:-github.com} (gh auth login)"
  return 0
fi

# github_web_list <title> <pr|issue> <gh json fields> <jq: one gh entry → one item>
github_web_list() {
  local out err
  err=$(mktemp)
  if out=$(cd "$HOST_CWD" && { [ -z "$gh_token" ] || export GH_TOKEN=$gh_token; } && timeout 30 gh "$2" list --limit 50 --json "$3" 2>"$err"); then
    web_list "$1" "$(jq -c "map($4)" <<<"$out")"
  else
    web_note "gh $2 list: $(head -n 1 "$err" | grep . || echo "failed or timed out")"
  fi
  rm -f "$err"
}

# A pull request's CI, from its checks (CheckRun: status + conclusion) and commit statuses
# (StatusContext: state): failing if any failed, else running if any is unfinished, else passing.
# Nothing when it has no checks at all.
# shellcheck disable=SC2016  # jq, not shell
github_ci='def ci:
  [(.statusCheckRollup // [])[] | if .__typename == "StatusContext" then .state
     elif .status != "COMPLETED" then "PENDING" else .conclusion end] as $s
  | ($s | length) as $n
  | ([$s[] | select(IN("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"))] | length) as $failed
  | ([$s[] | select(IN("PENDING", "EXPECTED"))] | length) as $running
  | if $n == 0 then {}
    elif $failed > 0 then {status: "fail", status_text: "CI: \($failed) of \($n) checks failed"}
    elif $running > 0 then {status: "pending", status_text: "CI: \($running) of \($n) checks running"}
    else {status: "ok", status_text: "CI: \($n) checks passed"} end;'

github_web_list "Pull requests" pr number,title,url,headRefName,isDraft,statusCheckRollup \
  "$github_ci"' {ref: "#\(.number)", title, url, branch: .headRefName}
    + (if .isDraft then {note: "Draft"} else {} end) + ci'
# Resolve: a session told to fix the issue, reading it in full itself (the title is all we send).
github_web_list "Issues" issue number,title,url '{ref: "#\(.number)", title, url, start: {label: "Resolve",
  task: "Resolve GitHub issue #\(.number): \(.title) (\(.url)). Read it in full first, with its comments: `gh issue view \(.number) --comments`. Then fix it: make the change, add or update tests and run them, commit, push your branch and open a pull request whose description says \"Closes #\(.number)\"."}}'
