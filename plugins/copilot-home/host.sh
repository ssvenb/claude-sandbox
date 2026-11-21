# shellcheck shell=bash
# Host stage: hand the agent a copy of your Copilot CLI config directory, credentials included — so
# no COPILOT_GITHUB_TOKEN is needed. A copy, not the directory itself: whatever the agent wrote into
# your own ~/.copilot (an MCP server, a hook) would run on this machine the next time Copilot starts
# here. The copy is the run's own, so a resumed run finds its session in it again (session-state/);
# nothing of it comes back to yours.
AGENT_AUTH_PROVIDED=1

COPILOT_HOME_SRC=${COPILOT_HOME_DIR:-$HOME/.copilot}
[ -d "$COPILOT_HOME_SRC" ] || die "copilot-home: there is no Copilot config directory at $COPILOT_HOME_SRC (COPILOT_HOME_DIR)."
COPILOT_HOME_RUN="${XDG_STATE_HOME:-$HOME/.local/state}/claude-sandbox/copilot-home/$RUN_ID"

# All but the run's own sessions goes, so the next start copies it afresh.
copilot_home_prune() {
  find "$COPILOT_HOME_RUN" -mindepth 1 -maxdepth 1 ! -name session-state -exec rm -rf -- {} +
}

mkdir -p -m 700 "$(dirname "$COPILOT_HOME_RUN")"
# A real directory, whatever a previous container of the run left there.
if [ -L "$COPILOT_HOME_RUN" ] || { [ -e "$COPILOT_HOME_RUN" ] && [ ! -d "$COPILOT_HOME_RUN" ]; }; then rm -f -- "$COPILOT_HOME_RUN"; fi
mkdir -p -m 700 "$COPILOT_HOME_RUN"
copilot_home_prune
(
  shopt -s dotglob nullglob
  for entry in "$COPILOT_HOME_SRC"/*; do
    [ "${entry##*/}" = session-state ] || cp -a -- "$entry" "$COPILOT_HOME_RUN/" || exit 1
  done
) || die "copilot-home: could not copy $COPILOT_HOME_SRC to $COPILOT_HOME_RUN"

pass_mount "$COPILOT_HOME_RUN" /home/node/.copilot
on_exit copilot_home_prune
