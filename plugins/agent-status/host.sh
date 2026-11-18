# shellcheck shell=bash
# Host stage: the webhook to tell when the agent goes idle or needs you, from the project's config —
#
#   { "plugins": { "agent-status": { "webhook": "https://hooks.slack.com/services/…" } } }
#
# None → the hook only colours the session's dot.

AGENT_STATUS_WEBHOOK=$(plugin_config '.webhook' '')
if [ -n "$AGENT_STATUS_WEBHOOK" ]; then
  pass_value AGENT_STATUS_WEBHOOK "$AGENT_STATUS_WEBHOOK"
  _project=${PROJECT_CONFIG_FILE:-$HOST_CWD}
  _project=${_project##*/}
  pass_value AGENT_STATUS_PROJECT "${_project%.json}"
  unset _project
fi
