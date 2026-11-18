# shellcheck shell=bash
# Web stage: the webhook host/notify.py tells when a session goes idle or needs you, run by the web
# server on each change of a session's status, from the project's config —
#
#   { "plugins": { "agent-status": { "webhook": "https://chat.googleapis.com/v1/spaces/…",
#                                     "webhookType": "google-chat" } } }   # or "generic", the default
#
# None → the hook only colours the session's dot.
_webhook=$(plugin_config '.webhook' '')
[ -z "$_webhook" ] || web_on_status "$PLUGIN_DIR/host/notify.py" "$_webhook" "$(plugin_config '.webhookType' generic)"
unset _webhook
