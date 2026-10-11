# shellcheck shell=bash
# Host stage: hand the container the host's KVM device.

[ -c /dev/kvm ] \
  || die "/dev/kvm not found — virtualisation off in firmware, or kvm module not loaded (disable the plugin with ENABLE_KVM=0)"

pass_arg --device /dev/kvm

# The device node keeps the host's numeric group, which usually doesn't exist in the container.
# root-init.sh needs the number to let the agent user open it on hosts where it isn't 0666.
pass_value KVM_DEVICE_GID "$(stat -c '%g' /dev/kvm)"

# Extra briefing for the agent, from .plugins.kvm.briefing in the project config: a string, or an
# array of lines (e.g. which disk images are mounted and how to boot them).
_kvm_briefing=$(plugin_config_json '.briefing' 'null' | jq -r 'if type == "array" then join("\n") elif . == null then "" else . end')
[ -z "$_kvm_briefing" ] || pass_value KVM_BRIEFING "$_kvm_briefing"
unset _kvm_briefing
