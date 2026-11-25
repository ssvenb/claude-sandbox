# shellcheck shell=bash
# Host stage: the tools the agent may sudo, from .plugins.permissions.tools. A build arg, so
# install.sh builds in the ones the image lacks, and a value, so root-init.sh writes their sudoers.

_perm_tools=$(plugin_config_json '.tools' '[]')
printf '%s' "$_perm_tools" | jq -e 'type == "array" and all(IN("apt", "npm", "pip", "chown", "mount", "network", "tcpdump", "strace"))' >/dev/null 2>&1 \
  || die "permissions: .plugins.permissions.tools in '$PROJECT_CONFIG_FILE' must list only: apt npm pip chown mount network tcpdump strace."
_perm_tools=$(printf '%s' "$_perm_tools" | jq -r 'unique | join(" ")')
if [ -n "$_perm_tools" ]; then
  pass_build_arg PERMISSIONS_TOOLS "$_perm_tools"
  pass_value PERMISSIONS_TOOLS "$_perm_tools"
fi
unset _perm_tools
