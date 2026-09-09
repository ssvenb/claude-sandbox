# shellcheck shell=bash
# Host stage: mirror the container's /workspace into a directory on this machine, so you can open
# what the agent is doing in an editor while it works. It only supplies the storage — git-workspace
# still clones into it and owns the branch. One directory per run.

AGENT_WORKSPACE_DIR="${AGENT_WORKSPACE_DIR:-$HOME/.agent-workspaces}"
run_dir="$AGENT_WORKSPACE_DIR/$(basename "$HOST_CWD")-$RUN_DATE-$RUN_ID"

# On --resume the date segment is the day the run was created, not today: reuse the directory that
# already carries this RUN_ID rather than opening a second one for the same run.
if [ "$RESUME" = 1 ]; then
  existing=$(ls -d "$AGENT_WORKSPACE_DIR"/*-"$RUN_ID" 2>/dev/null | head -n 1)
  [ -n "$existing" ] && run_dir="$existing"
fi

# `git clone` refuses a non-empty target, so the run directory has to start empty. Only reachable
# on --resume, where the re-clone fetches the branch back from origin: all that is lost is work the
# previous container never committed, which a run without this plugin loses anyway.
if [ -n "$(ls -A "$run_dir" 2>/dev/null)" ]; then
  echo "⚠️  Clearing $run_dir so the run can populate /workspace from scratch."
  rm -rf -- "${run_dir:?}"
fi

mkdir -p "$run_dir" || die "Cannot create AGENT_WORKSPACE_DIR: $run_dir"

pass_mount "$(cd "$run_dir" && pwd)" /workspace

echo "📂 /workspace is mirrored to $run_dir on this machine"

# Drop the mirror once the container is gone, so the runs don't pile up. host.sh is sourced into
# run.sh's shell, so an EXIT trap here fires after `docker run` returns — normal exit, failure or
# Ctrl-C alike. Anything the agent did not commit and push goes with it: set
# AGENT_WORKSPACE_CLEANUP=0 to keep the checkout around for inspection.
# ponytail: the only EXIT trap in the codebase; a second plugin wanting one needs a real post stage.
case "${AGENT_WORKSPACE_CLEANUP:-1}" in
  1|true|yes|on)
    trap 'echo "🧹 Removing $run_dir"; rm -rf -- "${run_dir:?}"' EXIT ;;
esac
