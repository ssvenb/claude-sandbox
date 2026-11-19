# shellcheck shell=bash
# Web stage: the project's open pull requests and issues, each linking to its GitHub page. Asked
# (host/github.py, the API through `requests`) with an installation token of the project's GitHub
# App (GH_AUTH), so the host needs no gh CLI: what the page does on GitHub (closing a pull request)
# is done as the App's bot. A project without one borrows the token of the host's own `gh` login
# when there is one — yours, as its GH_USERNAME when it names one (gh keeps a token per account).
#
# Issues get a section. Pull requests show only for the run a later plugin ties them to
# (git-workspace, by branch): on that run's session row, where they offer to be closed when the
# session is deleted (WEB_ACTION close-pr, run only once the page's user said yes); and an open
# one whose run has no session listed, under "Pull requests" on the project's panel, to resume.

git -C "$HOST_CWD" remote get-url origin >/dev/null 2>&1 || return 0

# github_app_token: an installation token of the project's App for its origin, in gh_token. The
# page asks every minute, and minting is two API calls, so one is kept for 40 minutes (tokens last
# 60) in a directory only this user can read; failing, the minter's complaint becomes a note.
github_app_token() {
  local origin dir file err
  origin=$(git -C "$HOST_CWD" remote get-url origin)
  dir=${XDG_CACHE_HOME:-$HOME/.cache}/claude-sandbox/github-auth
  file=$dir/$(printf '%s\n' "$GH_APP_ID" "${GH_HOST:-github.com}" "$origin" | cksum | cut -d" " -f1)
  if [ -n "$(find "$file" -mmin -40 2>/dev/null)" ]; then
    gh_token=$(cat "$file")
    return 0
  fi
  mkdir -p "$dir" && chmod 700 "$dir"
  err=$(mktemp)
  if gh_token=$(GH_APP_ID="$GH_APP_ID" GH_PRIVATE_KEY_FILE="$GH_PRIVATE_KEY_FILE" GH_HOST="${GH_HOST:-github.com}" \
       REPO_URL="$origin" timeout 30 "$PLUGIN_DIR/host/mint-gh-token.py" 2>"$err") && [ -n "$gh_token" ]; then
    (umask 077 && printf '%s' "$gh_token" >"$file.tmp" && mv -f "$file.tmp" "$file")
  else
    web_note "$(head -n 1 "$err" | grep . || echo "mint-gh-token: failed or timed out")"
    gh_token=
  fi
  rm -f "$err"
  [ -n "$gh_token" ]
}

gh_token=
if [ -n "${GH_APP_ID:-}" ] && [ -n "${GH_PRIVATE_KEY_FILE:-}" ]; then
  github_app_token || return 0
elif ! command -v gh >/dev/null; then
  web_note "no GitHub App set for this project (GH_AUTH)"
  return 0
# The project's account, not whichever one gh has active: a host logged in to several picks per project.
elif ! gh_token=$(gh auth token --hostname "${GH_HOST:-github.com}" ${GH_USERNAME:+--user "$GH_USERNAME"} 2>/dev/null); then
  web_note "gh is not logged in${GH_USERNAME:+ as $GH_USERNAME} on ${GH_HOST:-github.com} (gh auth login)"
  return 0
fi

# github <github.py args…>: host/github.py on the project's repo, as its account, its output in
# github_out; when it fails, its first line of complaint becomes a note. Not in a subshell, or the
# note would be lost.
github() {
  local err rc=0
  err=$(mktemp)
  github_out=$(GH_TOKEN=$gh_token GH_HOST="${GH_HOST:-github.com}" REPO_URL="$(git -C "$HOST_CWD" remote get-url origin)" \
    timeout 30 python3 "$PLUGIN_DIR/host/github.py" "$@" 2>"$err") || rc=$?
  [ "$rc" = 0 ] || web_note "github $1: $(head -n 1 "$err" | grep . || echo "failed or timed out")"
  rm -f "$err"
  return "$rc"
}

if [ -n "${WEB_ACTION:-}" ]; then
  case "$WEB_ACTION:$WEB_ACTION_ARG" in
    close-pr:[1-9]*)
      [[ "$WEB_ACTION_ARG" =~ ^[0-9]+$ ]] || { web_note "not a pull request number: $WEB_ACTION_ARG"; return 0; }
      github close "$WEB_ACTION_ARG" "Closed from the sandbox's web UI, with the session that worked on it." >/dev/null &&
        web_action_done ;;
    *) web_note "github-auth has no web action '$WEB_ACTION' for '$WEB_ACTION_ARG'" ;;
  esac
  return 0
fi

# github_items <open|merged|issues> <jq: one entry → one item>: the items of that list of
# `github list`'s, in github_items.
github_items() {
  github_items=$(jq -c ".$1 | map($2)" <<<"$github_out")
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

# The web server describes the project every minute, page or no page: CI turning green is an
# event other plugins act on (pr-review).
web_poll 60

github list || return 0
# Open pull requests, with their CI, offering to be closed with their run's session…
github_items open "$github_ci"' {ref: "#\(.number)", title, url, branch: .headRefName, sha: .headRefOid, section: "Pull requests",
    on_delete: {action: "close-pr", arg: "\(.number)",
      ask: "Pull request #\(.number), \"\(.title)\", is still open. Close it on GitHub too? (Cancel leaves it open.)"}}
    + (if .isDraft then {note: "Draft"} else {} end) + ci'
web_run_items "$github_items"
# …and merged ones, so a session shows its work went in: status "done", nothing left to close.
github_items merged '{ref: "#\(.number)", title, url, branch: .headRefName, note: "Merged", status: "done", status_text: "Merged"}'
web_run_items "$github_items"
# Resolve: a session told to fix the issue, reading it in full itself (the title is all we send);
# seeing its pull request's CI through to green is in every session's briefing (agent-init.sh).
# shellcheck disable=SC2016  # jq, not shell
github_items issues '{ref: "#\(.number)", title, url, start: {label: "Resolve",
  task: "Resolve GitHub issue #\(.number): \(.title) (\(.url)). Read it in full first, with its comments: `gh issue view \(.number) --comments`. Then fix it: make the change, add or update tests and run them, commit, push your branch and open a pull request whose description says \"Closes #\(.number)\"."}}'
web_list Issues "$github_items"
return 0
