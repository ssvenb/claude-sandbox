# shellcheck shell=bash
# Host stage: hand the container the host's KVM device.

[ -c /dev/kvm ] \
  || die "/dev/kvm not found — virtualisation off in firmware, or kvm module not loaded (disable the plugin with ENABLE_KVM=0)"

pass_arg --device /dev/kvm

# The device node keeps the host's numeric group, which usually doesn't exist in the container.
# root-init.sh needs the number to let the agent user open it on hosts where it isn't 0666.
pass_value KVM_DEVICE_GID "$(stat -c '%g' /dev/kvm)"
