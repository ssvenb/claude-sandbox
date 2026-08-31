# shellcheck shell=sh
# Agent stage (runs as 'node'). Prepares Copilot CLI's config/state directory.

# The binary lives in root-owned /usr/local/bin, so let the version stay pinned at image build
# time instead of having the CLI try to update itself.
export COPILOT_AUTO_UPDATE=false
export COPILOT_HOME="$HOME/.copilot"
mkdir -p "$COPILOT_HOME"

# Trust /workspace up front: the CLI otherwise opens with a "do you trust the files in this
# folder?" prompt, which stalls an unattended run. The binary treats this variable as blanket
# trust (it short-circuits the folder-trust check), matching the --allow-all posture launch.sh
# already uses — the sandbox is the boundary, not the prompts. Set as an env var rather than
# written into $COPILOT_HOME/config.json, which the copilot-home plugin may have bind-mounted
# from the host.
export COPILOT_ALLOW_ALL=true
