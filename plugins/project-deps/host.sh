# shellcheck shell=bash
# Host stage: read the repo's setup commands from the project config and validate them before the
# image is built, so a typo fails here rather than half-way through the container's boot.
#
#   { "plugins": { "project-deps": { "setup": ["make bootstrap"] } } }
#
# They run as the unprivileged agent user in the provisioned /workspace (agent-init.sh). Packages
# are build-tools' job: they go into the image. Nothing configured → the plugin does nothing.

# Setup commands are shell, so JSON's own "a list of strings" is all the validation there is. They
# cross over as JSON and are run one at a time by agent-init.sh.
PROJECT_DEPS_SETUP=$(plugin_config_json '.setup' '[]')
printf '%s' "$PROJECT_DEPS_SETUP" | jq -e 'type == "array" and all(type == "string")' >/dev/null 2>&1 \
  || die "project-deps: .plugins[\"project-deps\"].setup in '$PROJECT_CONFIG_FILE' must be an array of strings."
PROJECT_DEPS_SETUP_COUNT=$(printf '%s' "$PROJECT_DEPS_SETUP" | jq 'length')
if [ "$PROJECT_DEPS_SETUP_COUNT" != 0 ]; then
  pass_value PROJECT_DEPS_SETUP "$PROJECT_DEPS_SETUP"
  echo "📦 project-deps: $PROJECT_DEPS_SETUP_COUNT setup command(s)"
else
  echo "ℹ️  project-deps: nothing configured in '$PROJECT_CONFIG_FILE'; no setup commands run."
fi
unset PROJECT_DEPS_SETUP PROJECT_DEPS_SETUP_COUNT
