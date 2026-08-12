# shellcheck shell=bash
# Host stage: hand Claude Code its API credentials. Runs after the plugin host stage, so a plugin
# that brings its own credentials (claude-home) has already set AGENT_AUTH_PROVIDED.

[ "${AGENT_AUTH_PROVIDED:-0}" = 1 ] \
  || : "${CLAUDE_CODE_OAUTH_TOKEN:?CLAUDE_CODE_OAUTH_TOKEN must be set in .env (generate one with 'claude setup-token')}"

pass_env CLAUDE_CODE_OAUTH_TOKEN
