# shellcheck shell=bash
# Host stage. The NetBird PAT — which can enumerate and manage every peer — stays on this machine;
# the container gets only a setup key, which can do nothing but enrol one peer into the group the
# key was minted for. Mint it out-of-band and put it in .env as NB_SETUP_KEY. Prefer a key that is
# *ephemeral* (the peer self-removes with the container) and, if you resume runs, *reusable*.

# WireGuard needs a tun device and the capability to configure interfaces and routes. Bridge
# networking is deliberately kept (never --network host), so the peer lives in the container's own
# netns and cannot see the host's mesh traffic.
[ -e /dev/net/tun ] || die "netbird needs /dev/net/tun on the host (load the 'tun' kernel module)."
pass_arg --cap-add=NET_ADMIN --device=/dev/net/tun

pass_value NB_SETUP_KEY "$NB_SETUP_KEY"
# Self-hosted management server; unset means NetBird Cloud.
pass_env NB_MANAGEMENT_URL
# Peer name; defaults to sandbox-$RUN_ID in the container, where RUN_ID is known.
pass_env NB_HOSTNAME
