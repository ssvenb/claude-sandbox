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
# git, like bin/gh: every repo with the read-only token (plus issues), the run's own with gh's login.
git config --global --replace-all "credential.https://$GH_HOST.helper" ''
git config --global --add "credential.https://$GH_HOST.helper" \
  '!GH_TOKEN=$(cat /run/credentials/github-token-all) /usr/bin/gh auth git-credential'
case "${REPO_URL:-}" in
  "https://$GH_HOST/"*)
    for url in "${REPO_URL%.git}" "${REPO_URL%.git}.git"; do
      git config --global --replace-all "credential.$url.helper" ''
      git config --global --add "credential.$url.helper" '!/usr/bin/gh auth git-credential'
    done ;;
esac
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

When your work changes what the UI looks like, show it in the pull request's description with
screenshots of the changed views (light and dark, if the UI has both). Commit the images under
`.github/pr-screenshots/`, push, remove them again in the next commit so the final diff does not
carry them, and link them by the first commit's SHA:
`![what it shows](https://github.com/OWNER/NAME/blob/<sha>/.github/pr-screenshots/<file>.png?raw=true)`.

Leave whole test suites to GitHub CI, which runs the unit tests on every push: push your branch
and watch its checks instead of running a full suite locally. Locally, run only the selection of
tests that covers what you changed.

If the sandbox itself gets in your way (a hook blocks something it should not, a tool or
credential is missing, its instructions are wrong or unclear), file an issue on the sandbox's
own repository: `gh issue create --repo ssvenb/claude-sandbox`. Say what you ran, what happened
and what you expected, and tell the user you filed it. Filing is all you can do there: you
cannot comment on, close or reopen those issues (GraphQL answers "Resource not accessible by
integration"), and that is intended. Once you have filed one, following it up is the user's job.
Problems with the project you are working on go to the user, not there.

You have two GitHub tokens, both re-minted every 40 minutes. `/run/credentials/github-token` is
scoped to this run's repository (push, pull requests, issues, CI) and is what `gh` is logged in
with. `/run/credentials/github-token-all` reaches every other repository of the GitHub App,
read-only except that it may create issues (not comment on or close them). `gh` (a wrapper at `/usr/local/bin/gh`) and
git pick the token by the repository a command targets: `-R/--repo`, `gh api repos/OWNER/NAME/…`,
`gh repo <cmd> OWNER/NAME`, else the current directory's origin. If a call is refused (401, 403,
or 404 on a repository that exists), it probably went out with the wrong token: name the
repository with `--repo`, or set it yourself, e.g.
`GH_TOKEN=$(cat /run/credentials/github-token-all) /usr/bin/gh …`. Writing anything but issues
to another repository is not possible.
BRIEF
