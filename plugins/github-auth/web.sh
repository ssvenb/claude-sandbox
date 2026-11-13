# shellcheck shell=bash
# Web stage: the project's open pull requests and issues, each linking to its GitHub page. Asked
# through the host's own `gh` login — yours, as the project's GH_USERNAME when it names one (gh
# keeps a token per account); the App's tokens are for the container.
#
# Issues get a section; pull requests none: they show only on the session row of the run a later
# plugin ties them to (git-workspace, by branch), and offer to be closed when that session is
# deleted (WEB_ACTION close-pr, run only once the page's user said yes).

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

# github_gh <gh args…>: gh in the project, as its account, its output in github_out; when it
# fails, its first line of complaint becomes a note. Not in a subshell, or the note would be lost.
github_gh() {
  local err rc=0
  err=$(mktemp)
  github_out=$(cd "$HOST_CWD" && { [ -z "$gh_token" ] || export GH_TOKEN=$gh_token; } && timeout 30 gh "$@" 2>"$err") || rc=$?
  [ "$rc" = 0 ] || web_note "gh $1 $2: $(head -n 1 "$err" | grep . || echo "failed or timed out")"
  rm -f "$err"
  return "$rc"
}

if [ -n "${WEB_ACTION:-}" ]; then
  case "$WEB_ACTION:$WEB_ACTION_ARG" in
    close-pr:[1-9]*)
      [[ "$WEB_ACTION_ARG" =~ ^[0-9]+$ ]] || { web_note "not a pull request number: $WEB_ACTION_ARG"; return 0; }
      github_gh pr close "$WEB_ACTION_ARG" --comment "Closed from the sandbox's web UI, with the session that worked on it." >/dev/null &&
        web_action_done ;;
    *) web_note "github-auth has no web action '$WEB_ACTION' for '$WEB_ACTION_ARG'" ;;
  esac
  return 0
fi

# github_items <pr|issue> <gh json fields> <jq: one gh entry → one item> [gh list args…]: the
# items in github_items; fails (with a note) when gh does.
github_items() {
  github_gh "$1" list --limit 50 --json "$2" "${@:4}" || return 1
  github_items=$(jq -c "map($3)" <<<"$github_out")
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

# Open pull requests, with their CI, offering to be closed with their run's session…
if github_items pr number,title,url,headRefName,isDraft,statusCheckRollup \
  "$github_ci"' {ref: "#\(.number)", title, url, branch: .headRefName,
    on_delete: {action: "close-pr", arg: "\(.number)",
      ask: "Pull request #\(.number), \"\(.title)\", is still open. Close it on GitHub too? (Cancel leaves it open.)"}}
    + (if .isDraft then {note: "Draft"} else {} end) + ci'; then
  web_run_items "$github_items"
  # …and merged ones, so a session shows its work went in: status "done", nothing left to close.
  github_items pr number,title,url,headRefName \
  '{ref: "#\(.number)", title, url, branch: .headRefName, note: "Merged", status: "done", status_text: "Merged"}' \
  --state merged && web_run_items "$github_items"
fi
# Resolve: a session told to fix the issue, reading it in full itself (the title is all we send);
# seeing its pull request's CI through to green is in every session's briefing (agent-init.sh).
# shellcheck disable=SC2016  # jq, not shell
github_items issue number,title,url '{ref: "#\(.number)", title, url, start: {label: "Resolve",
  task: "Resolve GitHub issue #\(.number): \(.title) (\(.url)). Read it in full first, with its comments: `gh issue view \(.number) --comments`. Then fix it: make the change, add or update tests and run them, commit, push your branch and open a pull request whose description says \"Closes #\(.number)\"."}}' && web_list Issues "$github_items"
return 0
