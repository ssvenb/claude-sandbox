# shellcheck shell=sh
# Container-side plugin framework. Sourced by entrypoint.sh (root) and agent-setup.sh (node).
#
# $ENABLED_PLUGINS was already resolved and validated on the host by run.sh; here we only run
# the stage scripts of the plugins it names.

PLUGIN_ROOT="${PLUGIN_ROOT:-/opt/plugins}"

# Run one lifecycle stage ("root-init" / "agent-init") across every enabled plugin, in order.
# Scripts are SOURCED, so their exports reach the rest of the boot sequence.
plugin_run_stage() {
  _stage="$1"
  for PLUGIN_NAME in ${ENABLED_PLUGINS:-}; do
    PLUGIN_DIR="$PLUGIN_ROOT/$PLUGIN_NAME"
    if [ ! -d "$PLUGIN_DIR" ]; then
      echo "⚠️  Unknown plugin '$PLUGIN_NAME' — skipping" >&2
      continue
    fi
    if [ -f "$PLUGIN_DIR/$_stage.sh" ]; then
      export PLUGIN_NAME PLUGIN_DIR
      # shellcheck disable=SC1090  # path resolved at runtime
      . "$PLUGIN_DIR/$_stage.sh"
    fi
  done
  unset _stage PLUGIN_NAME PLUGIN_DIR
}

# Print the settings.json fragments contributed by enabled plugins, in order.
plugin_settings_files() {
  for _name in ${ENABLED_PLUGINS:-}; do
    [ -f "$PLUGIN_ROOT/$_name/settings.json" ] && echo "$PLUGIN_ROOT/$_name/settings.json"
  done
  unset _name
  return 0
}

# Print every env var enabled plugins declare as a secret, so root can drop them before
# handing control to the unprivileged agent user.
plugin_secret_vars() {
  for _name in ${ENABLED_PLUGINS:-}; do
    [ -f "$PLUGIN_ROOT/$_name/plugin.json" ] &&
      jq -r '.secrets // [] | .[]' "$PLUGIN_ROOT/$_name/plugin.json"
  done
  unset _name
  return 0
}
