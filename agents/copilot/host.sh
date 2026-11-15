# shellcheck shell=bash
# Host stage: hand Copilot CLI its API credentials. Runs after the plugin host stage, so a plugin
# that brings its own has already set AGENT_AUTH_PROVIDED.
#
# Needs a fine-grained PAT with the "Copilot Requests" permission or a Copilot/gh OAuth token; the
# installation tokens github-auth mints are NOT accepted, hence its own variable.

[ "${AGENT_AUTH_PROVIDED:-0}" = 1 ] \
  || : "${COPILOT_GITHUB_TOKEN:?COPILOT_GITHUB_TOKEN must be set when AGENT=copilot: export it in your shell, or put it in the "env" block of .claude-sandbox.json (fine-grained PAT with the 'Copilot Requests' permission)}"

pass_env COPILOT_GITHUB_TOKEN
