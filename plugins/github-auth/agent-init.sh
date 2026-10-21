# shellcheck shell=sh
# Agent stage: authenticate gh — and through it git — with the installation token the host minted.
# The App key never enters the container; the host re-mints the token every 40 min and replaces
# the file, so hand each new one to gh as it arrives.

export GH_HOST="${GH_HOST:-github.com}"
GH_TOKEN_FILE=/run/credentials/github-token
gh auth login --hostname "$GH_HOST" --with-token <"$GH_TOKEN_FILE"
gh auth setup-git --hostname "$GH_HOST"
echo "✅ GitHub CLI authenticated successfully for the Agent!"

(
  last=$(cat "$GH_TOKEN_FILE")
  while sleep 60; do
    token=$(cat "$GH_TOKEN_FILE") || continue
    [ "$token" != "$last" ] || continue
    printf '%s\n' "$token" | gh auth login --hostname "$GH_HOST" --with-token && last=$token
  done
) </dev/null >/dev/null 2>&1 &
unset GH_TOKEN_FILE
