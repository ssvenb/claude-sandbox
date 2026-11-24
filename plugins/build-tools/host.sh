# shellcheck shell=bash
# Host stage: hand the build what to install, as build args (see the Dockerfile). Unset "tools"
# passes nothing, so the Dockerfile's default (every recipe) applies; changing any list rebuilds
# the plugin layer.
#
#   { "plugins": { "build-tools": {
#       "tools": ["python-pip", "chromium"],
#       "apt":   ["ripgrep"], "npm": ["pnpm@9"], "pip": ["uv"]
#   } } }

_bt_tools=$(plugin_config_json '.tools')
if [ "$_bt_tools" != null ]; then
  printf '%s' "$_bt_tools" | jq -e 'type == "array" and all(IN("python-pip", "terraform", "ruff", "chromium", "playwright"))' >/dev/null 2>&1 \
    || die "build-tools: .plugins[\"build-tools\"].tools in '$PROJECT_CONFIG_FILE' must list only: python-pip terraform ruff chromium playwright."
  pass_build_arg BUILD_TOOLS "$(printf '%s' "$_bt_tools" | jq -r 'join(" ")')"
fi

# A package name, not a shell command: install.sh expands the lists unquoted, so anything that could
# smuggle in a second word is rejected. Covers the punctuation real specifiers use (pnpm@9,
# ruff==0.6.*, git+https://…).
for _bt_key in apt npm pip; do
  _bt_list=$(plugin_config_json ".$_bt_key" '[]')
  printf '%s' "$_bt_list" | jq -e 'type == "array" and all(type == "string" and test("^[A-Za-z0-9@._+:/~^=<>*-]+$"))' >/dev/null 2>&1 \
    || die "build-tools: .plugins[\"build-tools\"].$_bt_key in '$PROJECT_CONFIG_FILE' must be an array of package names (no spaces or shell metacharacters)."
  _bt_list=$(printf '%s' "$_bt_list" | jq -r 'join(" ")')
  [ -z "$_bt_list" ] || pass_build_arg "BUILD_TOOLS_${_bt_key^^}" "$_bt_list"
done
unset _bt_tools _bt_key _bt_list
