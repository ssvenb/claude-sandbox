# shellcheck shell=bash
# Host stage: read what the target repo needs from the project config and validate it before the
# image is built, so a typo fails here rather than half-way through the build or the boot.
#
#   { "plugins": { "project-setup": {
#       "tools": ["python-pip", "chromium"],
#       "apt":   ["ripgrep"], "npm": ["pnpm@9"], "pip": ["uv"],
#       "setup": ["uv sync", "npm ci --prefix web"]
#   } } }
#
# Tools and packages are build args (install.sh runs them during `docker build`; changing a list
# rebuilds the plugin layer). Setup commands run at boot as the unprivileged agent user in the
# provisioned /workspace (agent-init.sh): project-supplied shell never runs as root.

# Unset "tools" passes nothing, so the Dockerfile's default (every recipe) applies.
_ps_tools=$(plugin_config_json '.tools')
if [ "$_ps_tools" != null ]; then
  printf '%s' "$_ps_tools" | jq -e 'type == "array" and all(IN("python-pip", "terraform", "ruff", "chromium", "playwright"))' >/dev/null 2>&1 \
    || die "project-setup: .plugins[\"project-setup\"].tools in '$PROJECT_CONFIG_FILE' must list only: python-pip terraform ruff chromium playwright."
  pass_build_arg BUILD_TOOLS "$(printf '%s' "$_ps_tools" | jq -r 'join(" ")')"
fi

# A package name, not a shell command: install.sh expands the lists unquoted, so anything that could
# smuggle in a second word is rejected. Covers the punctuation real specifiers use (pnpm@9,
# ruff==0.6.*, git+https://…).
for _ps_key in apt npm pip; do
  _ps_list=$(plugin_config_json ".$_ps_key" '[]')
  printf '%s' "$_ps_list" | jq -e 'type == "array" and all(type == "string" and test("^[A-Za-z0-9@._+:/~^=<>*-]+$"))' >/dev/null 2>&1 \
    || die "project-setup: .plugins[\"project-setup\"].$_ps_key in '$PROJECT_CONFIG_FILE' must be an array of package names (no spaces or shell metacharacters)."
  _ps_list=$(printf '%s' "$_ps_list" | jq -r 'join(" ")')
  [ -z "$_ps_list" ] || pass_build_arg "BUILD_TOOLS_${_ps_key^^}" "$_ps_list"
done

# Setup commands are shell, so JSON's own "a list of strings" is all the validation there is. They
# cross over as JSON and are run one at a time by agent-init.sh.
_ps_setup=$(plugin_config_json '.setup' '[]')
printf '%s' "$_ps_setup" | jq -e 'type == "array" and all(type == "string")' >/dev/null 2>&1 \
  || die "project-setup: .plugins[\"project-setup\"].setup in '$PROJECT_CONFIG_FILE' must be an array of strings."
if [ "$(printf '%s' "$_ps_setup" | jq 'length')" != 0 ]; then
  pass_value PROJECT_SETUP "$_ps_setup"
  echo "📦 project-setup: $(printf '%s' "$_ps_setup" | jq 'length') setup command(s)"
fi
unset _ps_tools _ps_key _ps_list _ps_setup
