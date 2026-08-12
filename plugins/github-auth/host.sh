# shellcheck shell=bash
# Host stage. The App private key stays on this machine; only its contents ride into the
# container, where root — and only root — turns them into 1h installation tokens.

[ -f "$GH_PRIVATE_KEY_FILE" ] || die "GH_PRIVATE_KEY_FILE not found: $GH_PRIVATE_KEY_FILE"

pass_env GH_APP_ID
pass_value GH_HOST "${GH_HOST:-github.com}"
pass_value GH_PRIVATE_KEY "$(cat "$GH_PRIVATE_KEY_FILE")"
