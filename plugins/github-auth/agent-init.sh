# shellcheck shell=sh
# Agent stage: authenticate with the installation token minted by root. The App key never
# reaches node; root re-mints this token in the background so the session outlives the 1h expiry.

export GH_HOST="${GH_HOST:-github.com}"
echo "$GH_INITIAL_TOKEN" | gh auth login --hostname "$GH_HOST" --with-token
gh auth setup-git --hostname "$GH_HOST"
echo "✅ GitHub CLI authenticated successfully for the Agent!"
