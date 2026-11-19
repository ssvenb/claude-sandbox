# shellcheck shell=bash
# Host stage: hand Claude Code its API credentials. Runs after the plugin host stage, so a plugin
# that brings its own credentials (claude-home) has already set AGENT_AUTH_PROVIDED.

[ "${AGENT_AUTH_PROVIDED:-0}" = 1 ] \
  || : "${CLAUDE_CODE_OAUTH_TOKEN:?Claude Code needs credentials: set CLAUDE_AUTH to a claude-token authentication (from 'claude setup-token'), or enable claude-home}"

pass_env CLAUDE_CODE_OAUTH_TOKEN

# Effort level for the run; launch.sh defaults to "low" when this is unset.
case "${CLAUDE_EFFORT:-}" in
  ""|low|medium|high|xhigh|max) pass_env CLAUDE_EFFORT ;;
  *) die "CLAUDE_EFFORT must be one of: low, medium, high, xhigh, max (got: $CLAUDE_EFFORT)" ;;
esac
pass_env CLAUDE_MODEL  # unset: Claude Code's own default model
