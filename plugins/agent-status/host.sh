# shellcheck shell=bash
# Host stage: the webhook to tell when the agent goes idle or needs you, from the project's config —
#
#   { "plugins": { "agent-status": { "webhook": "https://chat.googleapis.com/v1/spaces/…",
#                                     "webhookType": "google-chat" } } }   # or "generic", the default
#
# None → the hook only colours the session's dot.

AGENT_STATUS_WEBHOOK=$(plugin_config '.webhook' '')
if [ -n "$AGENT_STATUS_WEBHOOK" ]; then
  pass_value AGENT_STATUS_WEBHOOK "$AGENT_STATUS_WEBHOOK"
  pass_value AGENT_STATUS_WEBHOOK_TYPE "$(plugin_config '.webhookType' generic)"
  _project=${PROJECT_CONFIG_FILE:-$HOST_CWD}
  _project=${_project##*/}
  pass_value AGENT_STATUS_PROJECT "${_project%.json}"
  unset _project
fi
