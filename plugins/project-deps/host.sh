# shellcheck shell=bash
# Host stage: read what the target repo needs from the project config and validate it before the
# image is built, so a typo fails here rather than half-way through the container's boot.
#
#   { "plugins": { "project-deps": {
#       "apt":   ["ripgrep", "postgresql-client"],
#       "npm":   ["pnpm@9"],
#       "pip":   ["ruff"],
#       "setup": ["make bootstrap"]
#   } } }
#
# Packages are installed by root at boot (root-init.sh); "setup" commands run later as the
# unprivileged agent user in the provisioned /workspace — arbitrary project-supplied shell never
# runs in the privileged stage. Nothing configured → the plugin does nothing.

# A package name, not a shell command: the lists are expanded unquoted by apt/npm/pip, so anything
# that could smuggle in a second word or a redirection is rejected. Covers the punctuation real
# specifiers use (pnpm@9, ruff==0.6.*, git+https://…, ./local-pkg).
PROJECT_DEPS_NAME_RE='^[A-Za-z0-9@._+:/~^=<>*-]+$'
PROJECT_DEPS_SUMMARY=""

# Validate one list and hand it over as a space-separated string. Cannot print its result: a
# command substitution would run pass_value in a subshell, losing the append to DOCKER_ARGS.
project_deps_pass_list() {
  local key=$1 var=$2 json entry list
  json=$(plugin_config_json ".$key" '[]')
  printf '%s' "$json" | jq -e 'type == "array" and all(type == "string")' >/dev/null 2>&1 \
    || die "project-deps: .plugins[\"project-deps\"].$key in '$PROJECT_CONFIG_FILE' must be an array of strings."
  while read -r entry; do
    [ -n "$entry" ] || continue
    [[ $entry =~ $PROJECT_DEPS_NAME_RE ]] \
      || die "project-deps: '$entry' is not a valid $key package name (no spaces or shell metacharacters)."
  done < <(printf '%s' "$json" | jq -r '.[]')
  list=$(printf '%s' "$json" | jq -r 'join(" ")')
  [ -n "$list" ] || return 0
  pass_value "$var" "$list"
  PROJECT_DEPS_SUMMARY+=" $key($list)"
}

project_deps_pass_list apt PROJECT_DEPS_APT
project_deps_pass_list npm PROJECT_DEPS_NPM
project_deps_pass_list pip PROJECT_DEPS_PIP

# Setup commands are shell, so JSON's own "a list of strings" is all the validation there is. They
# cross over as JSON and are run one at a time by agent-init.sh.
PROJECT_DEPS_SETUP=$(plugin_config_json '.setup' '[]')
printf '%s' "$PROJECT_DEPS_SETUP" | jq -e 'type == "array" and all(type == "string")' >/dev/null 2>&1 \
  || die "project-deps: .plugins[\"project-deps\"].setup in '$PROJECT_CONFIG_FILE' must be an array of strings."
PROJECT_DEPS_SETUP_COUNT=$(printf '%s' "$PROJECT_DEPS_SETUP" | jq 'length')
if [ "$PROJECT_DEPS_SETUP_COUNT" != 0 ]; then
  pass_value PROJECT_DEPS_SETUP "$PROJECT_DEPS_SETUP"
  PROJECT_DEPS_SUMMARY+=" $PROJECT_DEPS_SETUP_COUNT setup command(s)"
fi

if [ -n "$PROJECT_DEPS_SUMMARY" ]; then
  echo "📦 project-deps:$PROJECT_DEPS_SUMMARY"
else
  echo "ℹ️  project-deps: nothing configured in '$PROJECT_CONFIG_FILE'; no dependencies installed."
fi

unset -f project_deps_pass_list
unset PROJECT_DEPS_NAME_RE PROJECT_DEPS_SUMMARY PROJECT_DEPS_SETUP PROJECT_DEPS_SETUP_COUNT
