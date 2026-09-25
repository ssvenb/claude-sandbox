# shellcheck shell=sh
# Agent stage: tell the agent it can run accelerated VMs.

[ -n "${AGENT_PROMPT_FILE:-}" ] || return 0

cat >> "$AGENT_PROMPT_FILE" <<'EOF'

KVM is available: /dev/kvm is passed through and QEMU is installed (qemu-system-*, qemu-img,
cloud-localds, OVMF firmware). Start VMs with `-accel kvm -cpu host`. There is no libvirt and no
bridge/TAP networking; use user-mode networking (`-netdev user,id=n0,hostfwd=tcp::2222-:22`).
EOF
