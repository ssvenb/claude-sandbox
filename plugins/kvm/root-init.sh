# shellcheck shell=sh
# Root stage: make /dev/kvm usable by the agent user. Many distros ship it 0660 root:kvm, and the
# host's kvm gid rarely matches the container's, so QEMU as 'node' fails with "Could not access KVM
# kernel module: Permission denied". Only root can fix the membership; it grants nothing beyond
# the device.

[ -n "${KVM_DEVICE_GID:-}" ] || return 0

# Reuse whatever group already holds that gid (the image's own 'kvm', if QEMU's packages made one).
_kvm_group=$(getent group "$KVM_DEVICE_GID" | cut -d: -f1)
if [ -z "$_kvm_group" ]; then
  _kvm_group=kvm-host
  groupadd -g "$KVM_DEVICE_GID" "$_kvm_group" 2>/dev/null \
    || echo "⚠️  Could not create group $_kvm_group (gid $KVM_DEVICE_GID)" >&2
fi
if ! id -nG node | tr ' ' '\n' | grep -qx "$_kvm_group"; then
  usermod -aG "$_kvm_group" node \
    && echo "🖥️  KVM: node added to $_kvm_group (gid $KVM_DEVICE_GID)" \
    || echo "⚠️  Could not add node to $_kvm_group" >&2
fi
unset _kvm_group
