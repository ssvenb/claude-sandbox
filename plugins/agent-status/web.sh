# shellcheck shell=bash
# Web stage: the webhook the web server tells when a session goes idle or needs you, from the
# project's config —
#
#   { "plugins": { "agent-status": { "webhook": "https://chat.googleapis.com/v1/spaces/…",
#                                     "webhookType": "google-chat" } } }   # or "generic", the default
#
# None → the hook only colours the session's dot.
_webhook=$(plugin_config '.webhook' '')
[ -z "$_webhook" ] || web_notify "$_webhook" "$(plugin_config '.webhookType' generic)"
unset _webhook
