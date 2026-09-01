# shellcheck shell=bash
# Host stage: drop the container's own network namespace and share the host's.
#
# The sandbox isolates the *filesystem and credentials* the agent can reach, not the network. With
# a shared namespace a dev server the agent starts on :3000 is simply on the host's :3000 — no -p
# to predict, no range to reserve, no collision between the port the agent picked and the port you
# published — and the agent can talk to services already listening on the host's localhost
# (a database, another dev server) the same way you would.
#
# The trade is symmetric, and worth stating: everything bound to the host's loopback is now in
# reach of an unattended agent, including anything that treats "came from localhost" as
# authentication. Bind ports it should not reach to a specific interface rather than 0.0.0.0, and
# keep this plugin off (ENABLE_HOST_NETWORK=0) on machines where that is not true.

pass_arg --network host
