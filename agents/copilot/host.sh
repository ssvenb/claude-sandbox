# shellcheck shell=bash
# Host stage: hand Copilot CLI its API credentials. Runs after the plugin host stage, so home.sh (your
# ~/.copilot) or a plugin that brings its own has already set AGENT_AUTH_PROVIDED.
#
# Needs a fine-grained PAT with the "Copilot Requests" permission or a Copilot/gh OAuth token; the
# installation tokens github-auth mints are NOT accepted, hence its own variable.

[ "${AGENT_AUTH_PROVIDED:-0}" = 1 ] \
  || : "${COPILOT_GITHUB_TOKEN:?Copilot needs credentials: pick a copilot-token authentication (a fine-grained PAT with the 'Copilot Requests' permission) as the GitHub token of the copilot agent, or switch its Mount ~/.copilot on}"

pass_env COPILOT_GITHUB_TOKEN
