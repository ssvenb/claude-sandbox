# shellcheck shell=bash
# Web stage: the project's open pull requests and issues, each linking to its GitHub page. Asked
# through the host's own `gh` login — yours; the App's tokens are for the container.

git -C "$HOST_CWD" remote get-url origin >/dev/null 2>&1 || return 0
if ! command -v gh >/dev/null; then
  web_note "the gh CLI is not installed on this machine"
  return 0
fi

# github_web_list <title> <pr|issue> <gh json fields> <jq: one gh entry → one item>
github_web_list() {
  local out err
  err=$(mktemp)
  if out=$(cd "$HOST_CWD" && timeout 30 gh "$2" list --limit 50 --json "$3" 2>"$err"); then
    web_list "$1" "$(jq -c "map($4)" <<<"$out")"
  else
    web_note "gh $2 list: $(head -n 1 "$err" | grep . || echo "failed or timed out")"
  fi
  rm -f "$err"
}

github_web_list "Pull requests" pr number,title,url,headRefName,isDraft \
  '{ref: "#\(.number)", title, url, branch: .headRefName} + (if .isDraft then {note: "Draft"} else {} end)'
github_web_list "Issues" issue number,title,url '{ref: "#\(.number)", title, url}'
