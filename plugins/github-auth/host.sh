# shellcheck shell=bash
# Host stage. The App private key stays on this machine: installation tokens are minted here, and
# the container only ever sees the current ones: /run/credentials/github-token, scoped to the run's
# repo (push, pull requests), and github-token-all, every repo of the App read-only plus issues.

# GH_APP_ID and GH_PRIVATE_KEY_FILE come from the github-app authentication GH_AUTH names (auth.json).
[ -f "$GH_PRIVATE_KEY_FILE" ] || die "github-auth: authentication '${GH_AUTH:-}' has no private key yet: upload it in the sandbox settings."
# The key is read by your own user (run.sh, and the refresher every 40 min), not by root.
[ -r "$GH_PRIVATE_KEY_FILE" ] || die "github-auth: the private key of authentication '${GH_AUTH:-}' is not readable by $(id -un): upload it in the sandbox settings again."

GITHUB_AUTH_DIR=$PLUGIN_DIR
# Called by the core after every host stage, so git-workspace's REPO_URL is set by then: it picks
# the installation that owns the repo.
github_auth_mint() {
  GH_APP_ID="$GH_APP_ID" GH_PRIVATE_KEY_FILE="$GH_PRIVATE_KEY_FILE" GH_HOST="${GH_HOST:-github.com}" \
    REPO_URL="${REPO_URL:-}" "$GITHUB_AUTH_DIR/host/mint-gh-token.py" "$@"
}
github_auth_mint_all() { github_auth_mint --all; }
# Installation tokens expire after 1h (hard GitHub limit); 40 min leaves room for failed attempts.
register_credential github-token 2400 github_auth_mint
register_credential github-token-all 2400 github_auth_mint_all

pass_value GH_HOST "${GH_HOST:-github.com}"
[ -z "${GH_USERNAME:-}" ] || pass_value GH_USERNAME "$GH_USERNAME"
