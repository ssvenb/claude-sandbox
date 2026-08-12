# shellcheck shell=sh
# Agent stage (runs as 'node'). Prepares Copilot CLI's config/state directory.

# The binary lives in root-owned /usr/local/bin, so let the version stay pinned at image build
# time instead of having the CLI try to update itself.
export COPILOT_AUTO_UPDATE=false
export COPILOT_HOME="$HOME/.copilot"
mkdir -p "$COPILOT_HOME"
