# shellcheck shell=bash
# Host stage: hand the container the host user's Claude config directory.

pass_mount "${CLAUDE_HOME_DIR:-$HOME/.claude}" /home/node/.claude
