# shellcheck shell=bash
# Web stage: where host.sh mirrors a run's /workspace, so the page can open it in VS Code. Found
# by the RUN_ID alone, as host.sh does on --resume: the date in the name is the day the run began.

web_checkout "${AGENT_WORKSPACE_DIR:-$HOME/.agent-workspaces}/*-{run_id}"
