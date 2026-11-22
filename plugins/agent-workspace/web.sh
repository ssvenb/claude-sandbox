# shellcheck shell=bash
# Web stage: where host.sh mirrors a run's /workspace, so the page (web/) can open it in VS Code.
# Found by the RUN_ID alone, as host.sh does on --resume: the date in the name is the day the run began.

web_checkout "${AGENT_WORKSPACE_DIR:-$HOME/.agent-workspaces}/*-{run_id}"

# VS Code in the browser, on our origin under /plugins/agent-workspace/: started on its first use,
# in a container of its own that sees the mirrors. shortcut: one VS Code for all projects sees only
# the first project's mirror directory; give each AGENT_WORKSPACE_DIR its own server if they differ.
web_server "$PLUGIN_DIR/host/vscode.py" "${AGENT_WORKSPACE_DIR:-$HOME/.agent-workspaces}"
