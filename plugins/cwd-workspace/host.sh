# shellcheck shell=bash
# Host stage. Unlike git-workspace this is a live bind-mount: the agent's edits land in the
# host directory immediately, with no branch isolation.

HOST_WORKSPACE_DIR="${HOST_WORKSPACE_DIR:-$PWD}"
[ -d "$HOST_WORKSPACE_DIR" ] || die "HOST_WORKSPACE_DIR is not a directory: $HOST_WORKSPACE_DIR"

pass_mount "$(cd "$HOST_WORKSPACE_DIR" && pwd)" /workspace
