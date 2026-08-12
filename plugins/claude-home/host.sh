# shellcheck shell=bash
# Host stage: hand the container the host user's Claude config directory.

# That directory carries its own credentials, so no OAuth token is needed.
CLAUDE_AUTH_PROVIDED=1

pass_mount "${CLAUDE_HOME_DIR:-$HOME/.claude}" /home/node/.claude
