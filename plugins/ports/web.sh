# shellcheck shell=bash
# Web stage: the proxy's published ports, as buttons on their sessions' rows.
web_live_items "$("$PLUGIN_DIR/host/lease.py" items)"
