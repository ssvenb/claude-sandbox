# shellcheck shell=bash
# Host stage: hand the container the host user's Copilot CLI config directory.

# That directory carries its own credentials, so no COPILOT_GITHUB_TOKEN is needed.
AGENT_AUTH_PROVIDED=1

pass_mount "${COPILOT_HOME_DIR:-$HOME/.copilot}" /home/node/.copilot
