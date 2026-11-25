# shellcheck shell=bash
# Per-project configuration, as plugins read it. Sourced by src/contract/host/stage.sh (bash, on YOUR
# machine); the file itself is loaded and checked by src/orchestrator/config.py.
#
# Settings that belong to the project the agent works on — its repo, which upstreams to proxy,
# which bucket to hand over — live in one JSON file per project (`run.sh --project my-app`):
#
#   ~/.config/claude-sandbox/projects/my-app.json
#   {
#     "repo": "~/code/my-app",
#     "agent": "copilot",
#     "plugins": {
#       "upstream-proxy": { "routes": [ ... ] },
#       "git-workspace": { "enabled": false, "baseBranch": "trunk" }
#     }
#   }
#
# The file and every key in it are optional. Nothing here is passed to the container — a plugin
# decides what, if anything, crosses over.

PROJECT_CONFIG_FILE="${PROJECT_CONFIG_FILE:-}"
# Whole file, compact, or empty when there is none: loaded and checked by src/orchestrator/config.py, which
# hands it to the stage in the environment.
PROJECT_CONFIG_JSON="${PROJECT_CONFIG_JSON:-}"

# project_plugin_setting <plugin> <jq-filter> [default] — one scalar from a plugin's section.
# Names the plugin explicitly, for callers outside a plugin stage.
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
