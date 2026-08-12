# shellcheck shell=sh
# Root stage: the only context that holds $GH_PRIVATE_KEY, which entrypoint.sh drops before
# handing control to the agent user.

# Host every GitHub call targets: github.com, or an Enterprise Server hostname. Exported so gh
# picks it up in both the refresh loop below and the agent's own shell.
export GH_HOST="${GH_HOST:-github.com}"

GH_INITIAL_TOKEN=$("$PLUGIN_DIR/root/mint-gh-token.py")
export GH_INITIAL_TOKEN

# Installation tokens expire after 1h (hard GitHub limit). Re-mint in the background as root and
# push the fresh token into node's gh auth (read by both git and gh). The App key stays in root's
# environment — node, a different uid, cannot read it.
(
  while sleep 2400; do   # 40 min, inside the 1h expiry
    T=$("$PLUGIN_DIR/root/mint-gh-token.py") || continue   # keep looping on transient failure
    su -s /bin/sh node -c "export HOME=/home/node GH_HOST='$GH_HOST'; echo '$T' | gh auth login --hostname '$GH_HOST' --with-token" \
      && echo "🔄 Refreshed GitHub installation token"
  done
) &
