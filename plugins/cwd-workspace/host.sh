# shellcheck shell=bash
# Host stage. Unlike git-workspace this is a live bind-mount: the agent's edits land in the
# host directory immediately, with no branch isolation.

HOST_WORKSPACE_DIR="${HOST_WORKSPACE_DIR:-$HOST_CWD}"
[ -d "$HOST_WORKSPACE_DIR" ] || die "HOST_WORKSPACE_DIR is not a directory: $HOST_WORKSPACE_DIR"
HOST_WORKSPACE_DIR=$(cd "$HOST_WORKSPACE_DIR" && pwd)

pass_mount "$HOST_WORKSPACE_DIR" /workspace

# A live mount carries the repo's own secrets in with it — .env by default. Shadow each listed
# path with a read-only /dev/null bind-mount: it reads as empty inside the container and the host
# file is untouched (a symlink or a delete would edit the user's real checkout). Space-separated,
# relative to the mounted directory; empty hides nothing.
CWD_WORKSPACE_HIDDEN=""
for rel in ${CWD_WORKSPACE_HIDE-.env}; do
  [ -f "$HOST_WORKSPACE_DIR/$rel" ] || continue
  pass_mount /dev/null "/workspace/$rel" ro
  CWD_WORKSPACE_HIDDEN="${CWD_WORKSPACE_HIDDEN:+$CWD_WORKSPACE_HIDDEN }/workspace/$rel"
done
if [ -n "$CWD_WORKSPACE_HIDDEN" ]; then
  pass_value CWD_WORKSPACE_HIDDEN "$CWD_WORKSPACE_HIDDEN"
  echo "🙈 cwd-workspace: hiding $CWD_WORKSPACE_HIDDEN from the container"
fi
