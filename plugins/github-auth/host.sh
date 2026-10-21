# shellcheck shell=bash
# Host stage. The App private key stays on this machine: installation tokens are minted here, and
# the container only ever sees the current one, as /run/credentials/github-token.

[ -f "$GH_PRIVATE_KEY_FILE" ] || die "GH_PRIVATE_KEY_FILE not found: $GH_PRIVATE_KEY_FILE"
command -v openssl >/dev/null || die "github-auth: openssl is required on the host to sign the App's JWT."

GITHUB_AUTH_DIR=$PLUGIN_DIR
# Called by the core after every host stage, so git-workspace's REPO_URL is set by then: it picks
# the installation that owns the repo.
github_auth_mint() {
  GH_APP_ID="$GH_APP_ID" GH_PRIVATE_KEY_FILE="$GH_PRIVATE_KEY_FILE" GH_HOST="${GH_HOST:-github.com}" \
    REPO_URL="${REPO_URL:-}" "$GITHUB_AUTH_DIR/host/mint-gh-token.py"
}
# Installation tokens expire after 1h (hard GitHub limit); 40 min leaves room for failed attempts.
register_credential github-token 2400 github_auth_mint

pass_value GH_HOST "${GH_HOST:-github.com}"
