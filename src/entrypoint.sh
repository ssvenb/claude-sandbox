#!/bin/sh
set -e

# Own the project files for the unprivileged agent user.
chown -R node:node /workspace

# Host every GitHub call targets: github.com, or an Enterprise Server hostname. Exported so gh
# picks it up in both the refresh loop below and the agent's own shell.
export GH_HOST="${GH_HOST:-github.com}"

# Mint the first installation token. Runs as ROOT, the only context that holds $GH_PRIVATE_KEY.
TOKEN=$(/usr/local/bin/mint-gh-token.py)

# Installation tokens expire after 1h (hard GitHub limit). Re-mint in the background as root and
# push the fresh token into node's gh auth (read by both git and gh). The App key stays in root's
# environment — node, a different uid, cannot read it.
(
  while sleep 2400; do   # 40 min, inside the 1h expiry
    T=$(/usr/local/bin/mint-gh-token.py) || continue   # keep looping on transient failure
    su -s /bin/sh node -c "export HOME=/home/node GH_HOST='$GH_HOST'; echo '$T' | gh auth login --hostname '$GH_HOST' --with-token" \
      && echo "🔄 Refreshed GitHub installation token"
  done
) &

# Hand off to 'node'. Drop the App key first so it never reaches the agent — node only ever sees
# short-lived tokens. -m preserves the curated env (GH_INITIAL_TOKEN, CLAUDE_CODE_OAUTH_TOKEN,
# REPO_URL, BASE_BRANCH, RUN_ID).
unset GH_PRIVATE_KEY GH_APP_ID
export GH_INITIAL_TOKEN="$TOKEN"
su -m -s /bin/sh node -c '/usr/local/bin/agent-setup.sh'
