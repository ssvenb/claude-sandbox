# shellcheck shell=bash
# Per-project configuration. Sourced by run.sh (bash, on YOUR machine).
#
# Settings that belong to the repo the agent works on — which upstreams to proxy, which bucket to
# hand over — live in one JSON file next to that checkout, so .env stays about the sandbox itself:
#
#   .claude-sandbox.json
#   {
#     "env": { "AGENT": "copilot", "ENABLE_GIT_WORKSPACE": 0 },
#     "plugins": {
#       "upstream-proxy": { "routes": [ ... ] },
#       "git-workspace": { "enabled": false }
#     }
#   }
#
# The file and every key in it are optional. Nothing here is passed to the container — a plugin
# decides what, if anything, crosses over.

PROJECT_CONFIG_FILE="${PROJECT_CONFIG_FILE:-${HOST_CWD:-$PWD}/.claude-sandbox.json}"
# Whole file, compact, or empty when there is none.
PROJECT_CONFIG_JSON=""

project_config_load() {
  [ -f "$PROJECT_CONFIG_FILE" ] || return 0
  jq -e 'type == "object"' "$PROJECT_CONFIG_FILE" >/dev/null 2>&1 \
    || die "Project config '$PROJECT_CONFIG_FILE' must be a JSON object."
  jq -e '(.plugins // {}) | type == "object"' "$PROJECT_CONFIG_FILE" >/dev/null 2>&1 \
    || die "Project config '$PROJECT_CONFIG_FILE': .plugins must be an object keyed by plugin name."
  jq -e '(.env // {}) | type == "object" and (all(.[]; type != "object" and type != "array"))' \
    "$PROJECT_CONFIG_FILE" >/dev/null 2>&1 \
    || die "Project config '$PROJECT_CONFIG_FILE': .env must be an object of scalar values."
  PROJECT_CONFIG_JSON=$(jq -c . "$PROJECT_CONFIG_FILE")
  echo "📄 Project config: $PROJECT_CONFIG_FILE"
}

# project_plugin_setting <plugin> <jq-filter> [default] — one scalar from a plugin's section.
# Names the plugin explicitly, for callers outside a plugin stage: plugins_resolve reads ".enabled"
# before any host.sh is sourced.
project_plugin_setting() {
  local out
  [ -n "$PROJECT_CONFIG_JSON" ] || { printf '%s' "${3-}"; return 0; }
  out=$(printf '%s' "$PROJECT_CONFIG_JSON" \
    | jq -r --arg p "$1" "(.plugins[\$p] // {}) | ($2) | select(. != null) | tostring")
  printf '%s' "${out:-${3-}}"
}

# --- helpers available to plugin host.sh scripts ---------------------------------------------
#
# Both read from .plugins["<the plugin being sourced>"], so a plugin never has to name itself.

# plugin_config <jq-filter> [default] — a scalar, e.g. plugin_config '.envFile' "$HOST_CWD/.env"
plugin_config() {
  project_plugin_setting "${PLUGIN_NAME:?plugin_config called outside a plugin stage}" "$1" "${2-}"
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
