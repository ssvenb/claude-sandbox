# shellcheck shell=sh
# Agent stage: authenticate gh — and through it git — with the installation token the host minted.
# The App key never enters the container; the host re-mints the token every 40 min and replaces
# the file, so hand each new one to gh as it arrives.

export GH_HOST="${GH_HOST:-github.com}"
GH_TOKEN_FILE=/run/credentials/github-token
# gh's git credential helper reports the host's `user`; every login resets it to the App's bot.
gh_set_user() { [ -z "${GH_USERNAME:-}" ] || gh config set -h "$GH_HOST" user "$GH_USERNAME" 2>/dev/null; }
gh auth login --hostname "$GH_HOST" --with-token <"$GH_TOKEN_FILE"
gh_set_user
gh auth setup-git --hostname "$GH_HOST"
echo "✅ GitHub CLI authenticated successfully for the Agent!"

(
  last=$(cat "$GH_TOKEN_FILE")
  while sleep 60; do
    token=$(cat "$GH_TOKEN_FILE") || continue
    [ "$token" != "$last" ] || continue
    printf '%s\n' "$token" | gh auth login --hostname "$GH_HOST" --with-token && { last=$token; gh_set_user; }
  done
) </dev/null >/dev/null 2>&1 &
unset GH_TOKEN_FILE

# The agent's work lands as a pull request, and only counts once its CI passes.
[ -n "${AGENT_PROMPT_FILE:-}" ] || return 0
cat >> "$AGENT_PROMPT_FILE" <<'BRIEF'

## Pull request and CI

This is informational context, not a task: wait for the user's. You are authenticated with
GitHub (`gh`, and git through it). Whenever you finish a task, always commit your work, push your
branch and open a pull request with `gh pr create` (or update the one already open for it). Then
watch its CI (`gh pr checks --watch`) until every check is green. If a check fails, or any other
problem comes up, read why (`gh run view --log-failed`), fix the cause, push the fix and watch CI
again. The task is not finished until the pull request's CI is green.
BRIEF
