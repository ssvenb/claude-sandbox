# shellcheck shell=sh
# Agent stage: start the project's server, and tell the agent it runs and how to restart it.
# Priority 28: after project-deps (25) installed what the server needs.

[ -n "${DEV_SERVER_COMMAND:-}" ] || return 0

# Sourced, so nothing here may exit: a server that will not start leaves the boot intact.
"$PLUGIN_DIR/bin/sandbox-server" start || echo "⚠️  dev-server: could not start: $DEV_SERVER_COMMAND" >&2

# shellcheck disable=SC2016  # backticks are markdown for the agent, not command substitution
{
  printf '\n## Dev server\n\n'
  printf 'The project'"'"'s server was started at boot, in /workspace, with `%s`; it reaches the ' "$DEV_SERVER_COMMAND"
  printf 'user on whichever of its ports the project publishes (see Ports). Control it with `%s/bin/sandbox-server ' "$PLUGIN_DIR"
  printf 'start|stop|restart|status|log` (its output goes to /tmp/sandbox-server.log), and restart '
  printf 'it after changes it does not pick up by itself.\n'
} >>"$AGENT_PROMPT_FILE"
