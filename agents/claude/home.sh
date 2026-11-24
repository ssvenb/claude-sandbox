# shellcheck shell=bash
# Home stage, before the plugins' (src/contract/host/agents.sh). CLAUDE_HOME_MOUNT (default on):
# hand the agent a copy of your Claude config directory, credentials included — so no OAuth token is
# needed. A copy, not the directory itself: the agent may write anything into what it is given, and
# hooks, plugins or settings it left in your own ~/.claude would run on this machine the next time
# Claude starts here, and in every later sandbox. The copy is the run's own, so a resumed run finds
# its conversation in it again; of what the agent changed, only a refreshed login comes back to yours
# (host/keep-credentials.py). The copies live at claude-sandbox/claude-home/<RUN_ID>, where a sign-in
# on the dashboard reaches those of the runs still going (after-sign-in.sh).
case "${CLAUDE_HOME_MOUNT:-${ENABLE_CLAUDE_HOME:-1}}" in  # ENABLE_CLAUDE_HOME: when it was a plugin
  1|true|yes|on) ;;
  0|false|no|off) return 0 ;;
  *) die "CLAUDE_HOME_MOUNT must be 0 or 1 (got: $CLAUDE_HOME_MOUNT)" ;;
esac
AGENT_AUTH_PROVIDED=1

CLAUDE_HOME_SRC=${CLAUDE_HOME_DIR:-$HOME/.claude}
[ -d "$CLAUDE_HOME_SRC" ] || die "claude: there is no Claude config directory at $CLAUDE_HOME_SRC (CLAUDE_HOME_DIR), or turn CLAUDE_HOME_MOUNT off."
CLAUDE_HOME_RUN="${XDG_STATE_HOME:-$HOME/.local/state}/claude-sandbox/claude-home/$RUN_ID"
CLAUDE_HOME_KEEP="$AGENT_DIR/host/keep-credentials.py"

# A directory at $1 that is really one: whatever else the agent left there (a symlink out of the
# copy, say) goes first, so nothing written into it lands elsewhere on this machine.
claude_home_dir() {
  if [ -L "$1" ] || { [ -e "$1" ] && [ ! -d "$1" ]; }; then rm -f -- "$1"; fi
  mkdir -p -- "$1"
}

# All but the run's own conversations (projects/) is dropped, so the next start copies it afresh.
claude_home_prune() {
  find "$CLAUDE_HOME_RUN" -mindepth 1 -maxdepth 1 ! -name projects -exec rm -rf -- {} +
}

# Every start: your current login and settings, none of what a previous container of this run left
# beside its conversations. Your other projects' conversations stay out; the memory of /workspace
# comes in, and what the agent writes to it stays in the copy.
mkdir -p -m 700 "$(dirname "$CLAUDE_HOME_RUN")"
claude_home_dir "$CLAUDE_HOME_RUN"
chmod 700 "$CLAUDE_HOME_RUN"
claude_home_prune
(
  shopt -s dotglob nullglob
  for entry in "$CLAUDE_HOME_SRC"/*; do
    [ "${entry##*/}" = projects ] || cp -a -- "$entry" "$CLAUDE_HOME_RUN/" || exit 1
  done
) || die "claude: could not copy $CLAUDE_HOME_SRC to $CLAUDE_HOME_RUN"
claude_home_dir "$CLAUDE_HOME_RUN/projects"
claude_home_dir "$CLAUDE_HOME_RUN/projects/-workspace"
rm -rf -- "$CLAUDE_HOME_RUN/projects/-workspace/memory"
[ ! -d "$CLAUDE_HOME_SRC/projects/-workspace/memory" ] \
  || cp -a -- "$CLAUDE_HOME_SRC/projects/-workspace/memory" "$CLAUDE_HOME_RUN/projects/-workspace/"

pass_mount "$CLAUDE_HOME_RUN" /home/node/.claude

# Once the container is gone: a login it refreshed goes back to yours (its old refresh token may be
# spent), then the copy shrinks to the run's conversations.
claude_home_leave() {
  "$CLAUDE_HOME_KEEP" "$CLAUDE_HOME_RUN/.credentials.json" "$CLAUDE_HOME_SRC/.credentials.json" || true
  claude_home_prune
}
on_exit claude_home_leave
