# shellcheck shell=bash
# Host stage: mirror the container's /workspace into a directory on this machine, so you can open
# what the agent is doing in an editor while it works. It only supplies the storage — git-workspace
# still clones into it and owns the branch. One directory per run.

AGENT_WORKSPACE_DIR="${AGENT_WORKSPACE_DIR:-$HOME/.agent-workspaces}"
# Named after the checkout, or for a git-URL project (no checkout) after the repo in the URL.
repo_name=$(basename "${HOST_CWD:-${REPO_URL:-repo}}" .git)
run_dir="$AGENT_WORKSPACE_DIR/${repo_name##*:}-$RUN_DATE-$RUN_ID"

# On --resume the date segment is the day the run was created, not today: reuse the directory that
# already carries this RUN_ID rather than opening a second one for the same run.
if [ "$RESUME" = 1 ]; then
  # `|| true`: run.sh runs under `set -eo pipefail`, so a no-match `ls` would abort the run.
  existing=$(ls -d "$AGENT_WORKSPACE_DIR"/*-"$RUN_ID" 2>/dev/null | head -n 1) || true
  [ -n "$existing" ] && run_dir="$existing"
fi

# agent_workspace_remove <dir>: delete a run's mirror. What the agent's own containers wrote into it
# (a database under docker-cli's daemon) belongs to a user of theirs, mapped by Sysbox to a uid that
# is not yours, so your `rm` cannot delete it: what is left is deleted by root in a throwaway
# container of the sandbox's image (no network, nothing else mounted), the directory itself by you.
agent_workspace_remove() {
  local dir=$1
  rm -rf -- "$dir" 2>/dev/null && return 0
  docker run --rm --pull never --network none --user 0 --entrypoint find -v "$dir:/mirror" \
    "claude-agent:${AGENT:-claude}" /mirror -mindepth 1 -delete >/dev/null 2>&1 || true
  rm -rf -- "$dir" 2>/dev/null && return 0
  echo "⚠️  agent-workspace: could not remove everything in $dir (files owned by another user, from" \
    "the agent's containers); remove it with: sudo rm -rf '$dir'" >&2
  return 1
}

# `git clone` refuses a non-empty target, so the run directory has to start empty. Only reachable
# on --resume, where the re-clone fetches the branch back from origin: all that is lost is work the
# previous container never committed, which a run without this plugin loses anyway.
if [ -n "$(ls -A "$run_dir" 2>/dev/null)" ]; then
  echo "⚠️  Clearing $run_dir so the run can populate /workspace from scratch."
  agent_workspace_remove "${run_dir:?}" || die "agent-workspace: $run_dir has to be empty for the run to start"
fi

mkdir -p "$run_dir" || die "agent-workspace: cannot create $run_dir in its workspaces directory"

pass_mount "$(cd "$run_dir" && pwd)" /workspace

echo "📂 /workspace is mirrored to $run_dir on this machine"

# Drop the mirror once the container is gone, so the runs don't pile up. host.sh is sourced into
# run.sh's shell, so an EXIT trap here fires after `docker run` returns — normal exit, failure or
# Ctrl-C alike. Anything the agent did not commit and push goes with it: set
# AGENT_WORKSPACE_CLEANUP=0 to keep the checkout around for inspection.
case "${AGENT_WORKSPACE_CLEANUP:-1}" in
  1|true|yes|on)
    on_exit "echo '🧹 Removing $run_dir'; agent_workspace_remove '${run_dir:?}' || true" ;;
esac
