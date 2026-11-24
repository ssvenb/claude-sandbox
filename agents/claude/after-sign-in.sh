# shellcheck shell=sh
# After a sign-in on this machine (the dashboard's "Sign in to Claude"): the new login goes into the
# copy of ~/.claude of every run still in a container (home.sh), so a running session does not
# stay signed out. A copy holds .credentials.json only while its container lives.
src=$(realpath -q -- "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/.credentials.json") || exit 0
for f in "${XDG_STATE_HOME:-$HOME/.local/state}"/claude-sandbox/claude-home/*/.credentials.json; do
  { [ -e "$f" ] || [ -L "$f" ]; } && "$(dirname -- "$0")/host/keep-credentials.py" "$src" "$f"
done
exit 0
