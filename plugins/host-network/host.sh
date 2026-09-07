# shellcheck shell=bash
# Host stage: share the host's network namespace instead of the container's own. A dev server the
# agent starts on :3000 is then simply the host's :3000 — no -p to predict, no collision — and the
# agent can reach services already listening on the host's localhost.
#
# The trade is symmetric: everything bound to the host's loopback is now in reach of an unattended
# agent, including anything that treats "came from localhost" as authentication. Bind such ports to
# a specific interface, or keep this plugin off (ENABLE_HOST_NETWORK=0).

pass_arg --network host
