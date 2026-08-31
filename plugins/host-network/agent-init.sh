# shellcheck shell=sh
# Agent stage: nothing to configure — the namespace is already shared. Just tell the agent, since
# the consequences are not visible from inside: a port it binds is the host's port (so a busy one
# means something on the host owns it, not a stale container), and localhost reaches the host's
# services.

echo "✅ Sharing the host's network namespace"
