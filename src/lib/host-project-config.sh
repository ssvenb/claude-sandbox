# shellcheck shell=bash
# Per-project configuration. Sourced by run.sh (bash, on YOUR machine).
#
# Some plugins need settings that belong to the repo the agent works on, not to the sandbox:
# which upstreams to proxy, which bucket to hand over, which hosts an ssh key is for. Those live
# in a single JSON file in the directory you launched run.sh from — $HOST_CWD — so a checkout can
# carry its own sandbox configuration while .env stays about the sandbox itself.
#
#   .claude-sandbox.json
#   {
#     "plugins": {
#       "upstream-proxy": { "routes": [ ... ] }
#     }
#   }
#
# The file is optional, and every key in it is optional: a plugin reads what it wants with
# `plugin_config` and falls back to its own default. Nothing here is passed to the container —
# it is host-side configuration, and a plugin decides what (if anything) crosses over.

PROJECT_CONFIG_FILE="${PROJECT_CONFIG_FILE:-${HOST_CWD:-$PWD}/.claude-sandbox.json}"
# Whole file, compact, or empty when there is none.
PROJECT_CONFIG_JSON=""

project_config_load() {
  [ -f "$PROJECT_CONFIG_FILE" ] || return 0
  jq -e 'type == "object"' "$PROJECT_CONFIG_FILE" >/dev/null 2>&1 \
    || die "Project config '$PROJECT_CONFIG_FILE' must be a JSON object."
  jq -e '(.plugins // {}) | type == "object"' "$PROJECT_CONFIG_FILE" >/dev/null 2>&1 \
    || die "Project config '$PROJECT_CONFIG_FILE': .plugins must be an object keyed by plugin name."
  PROJECT_CONFIG_JSON=$(jq -c . "$PROJECT_CONFIG_FILE")
  echo "📄 Project config: $PROJECT_CONFIG_FILE"
}

# --- helpers available to plugin host.sh scripts ---------------------------------------------
#
# Both read from .plugins["<the plugin being sourced>"], so a plugin never has to name itself.

# plugin_config <jq-filter> [default] — a scalar, e.g. plugin_config '.envFile' "$HOST_CWD/.env"
plugin_config() {
  local out
  [ -n "$PROJECT_CONFIG_JSON" ] || { printf '%s' "${2-}"; return 0; }
  out=$(printf '%s' "$PROJECT_CONFIG_JSON" \
    | jq -r --arg p "${PLUGIN_NAME:?plugin_config called outside a plugin stage}" \
        "(.plugins[\$p] // {}) | ($1) // empty")
  printf '%s' "${out:-${2-}}"
}

# plugin_config_json <jq-filter> [default-json] — a raw JSON value, for objects and arrays.
plugin_config_json() {
  local out
  [ -n "$PROJECT_CONFIG_JSON" ] || { printf '%s' "${2-null}"; return 0; }
  out=$(printf '%s' "$PROJECT_CONFIG_JSON" \
    | jq -c --arg p "${PLUGIN_NAME:?plugin_config_json called outside a plugin stage}" \
        "(.plugins[\$p] // {}) | ($1)")
  [ "$out" = null ] && out="${2-null}"
  printf '%s' "$out"
}
