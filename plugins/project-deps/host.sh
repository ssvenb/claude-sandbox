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
# Dependencies belong to the repo the agent works on, not to the sandbox, which is why they live
# in $PROJECT_CONFIG_FILE next to that checkout instead of in .env. With none configured the
# plugin does nothing, so it can stay on by default.
#
# Packages are installed by root at boot (root-init.sh); "setup" commands run later, as the
# unprivileged agent user in the provisioned /workspace, after the secrets have been dropped —
# arbitrary project-supplied shell never runs in the privileged stage.

# A package name, not a shell command: the list is expanded unquoted by apt/npm/pip, so anything
# that could smuggle in a second word or a redirection is rejected. Covers the punctuation real
# specifiers use (pnpm@9, ruff==0.6.*, git+https://…, ./local-pkg).
PROJECT_DEPS_NAME_RE='^[A-Za-z0-9@._+:/~^=<>*-]+$'

# Read one list, validate it, and hand it over as a space-separated string. Sets $PROJECT_DEPS_LIST
# rather than printing it: a command substitution would run pass_value in a subshell, where its
# append to DOCKER_ARGS would be lost.
project_deps_pass_list() {
  local key=$1 var=$2 json entry
  json=$(plugin_config_json ".$key" '[]')
  printf '%s' "$json" | jq -e 'type == "array" and all(type == "string")' >/dev/null 2>&1 \
    || die "project-deps: .plugins[\"project-deps\"].$key in '$PROJECT_CONFIG_FILE' must be an array of strings."
  while read -r entry; do
    [ -n "$entry" ] || continue
    [[ $entry =~ $PROJECT_DEPS_NAME_RE ]] \
      || die "project-deps: '$entry' is not a valid $key package name (no spaces or shell metacharacters)."
  done < <(printf '%s' "$json" | jq -r '.[]')
  PROJECT_DEPS_LIST=$(printf '%s' "$json" | jq -r 'join(" ")')
  [ -n "$PROJECT_DEPS_LIST" ] && pass_value "$var" "$PROJECT_DEPS_LIST"
  return 0
}

project_deps_pass_list apt PROJECT_DEPS_APT; PROJECT_DEPS_APT=$PROJECT_DEPS_LIST
project_deps_pass_list npm PROJECT_DEPS_NPM; PROJECT_DEPS_NPM=$PROJECT_DEPS_LIST
project_deps_pass_list pip PROJECT_DEPS_PIP; PROJECT_DEPS_PIP=$PROJECT_DEPS_LIST

# Setup commands are shell, so they only get the same validation JSON gives them: a list of
# strings. They cross over as JSON and are run one at a time by agent-init.sh.
PROJECT_DEPS_SETUP=$(plugin_config_json '.setup' '[]')
printf '%s' "$PROJECT_DEPS_SETUP" | jq -e 'type == "array" and all(type == "string")' >/dev/null 2>&1 \
  || die "project-deps: .plugins[\"project-deps\"].setup in '$PROJECT_CONFIG_FILE' must be an array of strings."
[ "$(printf '%s' "$PROJECT_DEPS_SETUP" | jq 'length')" != 0 ] \
  && pass_value PROJECT_DEPS_SETUP "$PROJECT_DEPS_SETUP"

if [ -n "$PROJECT_DEPS_APT$PROJECT_DEPS_NPM$PROJECT_DEPS_PIP" ] \
   || [ "$(printf '%s' "$PROJECT_DEPS_SETUP" | jq 'length')" != 0 ]; then
  echo "📦 project-deps:${PROJECT_DEPS_APT:+ apt($PROJECT_DEPS_APT)}${PROJECT_DEPS_NPM:+ npm($PROJECT_DEPS_NPM)}${PROJECT_DEPS_PIP:+ pip($PROJECT_DEPS_PIP)}${PROJECT_DEPS_SETUP:+ $(printf '%s' "$PROJECT_DEPS_SETUP" | jq 'length') setup command(s)}"
else
  echo "ℹ️  project-deps: nothing configured in '$PROJECT_CONFIG_FILE'; no dependencies installed."
fi

unset -f project_deps_pass_list
unset PROJECT_DEPS_NAME_RE PROJECT_DEPS_LIST PROJECT_DEPS_APT PROJECT_DEPS_NPM PROJECT_DEPS_PIP PROJECT_DEPS_SETUP
