# shellcheck shell=bash
# Host stage: the project's server command, from its config —
#
#   { "plugins": { "dev-server": { "command": "pnpm dev --port 3000" } } }
#
# No command → the plugin does nothing, which is why it can stay on by default.

DEV_SERVER_COMMAND=$(plugin_config '.command' '')
if [ -n "$DEV_SERVER_COMMAND" ]; then
  pass_value DEV_SERVER_COMMAND "$DEV_SERVER_COMMAND"
  echo "🚀 dev-server: starting \`$DEV_SERVER_COMMAND\` at boot"
fi
