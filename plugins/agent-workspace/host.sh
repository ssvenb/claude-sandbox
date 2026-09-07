# shellcheck shell=bash
# Host stage: mirror the container's /workspace into a directory on this machine, so you can open
# what the agent is doing in an editor while it works. It only supplies the storage — git-workspace
# still clones into it and owns the branch. One directory per run.

AGENT_WORKSPACE_DIR="${AGENT_WORKSPACE_DIR:-$HOME/.agent-workspace}"
run_dir="$AGENT_WORKSPACE_DIR/$RUN_ID"

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
