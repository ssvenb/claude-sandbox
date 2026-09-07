# shellcheck shell=sh
# Agent stage (runs as 'node'). Prepares Copilot CLI's config/state directory.

# The binary is root-owned, so keep the version pinned at image build time.
export COPILOT_AUTO_UPDATE=false
export COPILOT_HOME="$HOME/.copilot"
mkdir -p "$COPILOT_HOME"

# Blanket folder trust, matching launch.sh's --allow-all — otherwise the CLI opens with a "do you
# trust the files in this folder?" prompt that stalls an unattended run. An env var rather than
# $COPILOT_HOME/config.json, which the copilot-home plugin may have bind-mounted from the host.
export COPILOT_ALLOW_ALL=true
