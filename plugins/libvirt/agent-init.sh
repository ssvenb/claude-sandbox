# shellcheck shell=sh
# Agent stage: tell the agent it is driving the host's libvirt.

[ -n "${AGENT_PROMPT_FILE:-}" ] || return 0

cat >> "$AGENT_PROMPT_FILE" <<'BRIEF'

The host's libvirt is available: `virsh` talks to the host's system daemon (qemu:///system,
already the default URI). VMs, storage pools and networks you see are the HOST's — disks live in
host paths such as /var/lib/libvirt/images, not in this container, and VMs keep running after it
exits. Never delete or modify a domain or volume you did not create unless told to; clone instead.
BRIEF
