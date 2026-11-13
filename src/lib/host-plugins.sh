# shellcheck shell=bash
# Host-side plugin framework. Sourced by run.sh (bash, on YOUR machine).
#
# A plugin is a directory under plugins/ with a plugin.json manifest and optional lifecycle
# scripts, one per privilege stage:
#   host.sh        sourced here, on the host — validates config, appends to DOCKER_ARGS
#   web.sh         sourced here, on the host, by `run.sh --web` — what the web UI shows for a project
#   root-init.sh   sourced by entrypoint.sh as root, where secrets live
#   agent-init.sh  sourced by agent-setup.sh as the unprivileged 'node' user
#
# Enablement is resolved ONCE here and handed to the container as $ENABLED_PLUGINS, so the
# container never re-interprets the ENABLE_* flags.

PLUGIN_ROOT="${PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/plugins}"

# Every flag the plugins want on the `docker run` command line.
DOCKER_ARGS=()
# Every --build-arg the plugins want on the `docker build` command line.
BUILD_ARGS=()
# Space-separated, priority-ordered names of the plugins that will actually run.
ENABLED_PLUGINS=""
# Priority-ordered names of every plugin found on disk.
PLUGIN_LIST=()

die() { echo "❌ $*" >&2; exit 1; }

# ENABLE_ flag for a plugin: github-auth → ENABLE_GITHUB_AUTH.
plugin_flag_name() { printf 'ENABLE_%s' "$(printf '%s' "$1" | tr 'a-z-' 'A-Z_')"; }

# Every manifest's fields, read once by plugins_discover: one jq for all of them, not one per
# field and plugin (each jq start costs ~0.1 s on a small ARM host, which made `run.sh --web` slow).
# Keyed "<plugin> <field>"; list fields hold their entries space-separated.
declare -A PLUGIN_META=()
PLUGIN_META_FIELDS=(priority defaultEnabled requiredAgent conflicts requiredEnv provides requires)

# plugin_meta <plugin> <field>: one of PLUGIN_META_FIELDS, as plugins_discover read it.
plugin_meta() { printf '%s' "${PLUGIN_META["$1 $2"]-}"; }

# Names of the plugins (enabled or not) that advertise a given capability.
plugin_providers_of() {
  local p
  for p in "${PLUGIN_LIST[@]}"; do
    case " $(plugin_meta "$p" provides) " in *" $1 "*) echo "$p" ;; esac
  done
}

# --- helpers available to plugin host.sh scripts -------------------------------------------

# Forward host env vars into the container, skipping any that are unset or empty.
pass_env() {
  local var
  for var in "$@"; do
    [ -n "${!var:-}" ] && DOCKER_ARGS+=(-e "$var=${!var}")
  done
  return 0
}

# Forward a computed value the host has but the environment doesn't (e.g. a file's contents).
pass_value() { DOCKER_ARGS+=(-e "$1=$2"); }

# Raw `docker run` flags, for what an env var or a mount cannot express:
# pass_arg --cap-add=NET_ADMIN --device=/dev/net/tun
pass_arg() { DOCKER_ARGS+=("$@"); }

# Hand the image build a value (it must match an ARG in the Dockerfile). Build args land in the
# image history, so never a secret.
pass_build_arg() { BUILD_ARGS+=(--build-arg "$1=$2"); }

# pass_mount <host-path> <container-path> [options]
pass_mount() {
  local host_path=$1 container_path=$2 options=${3:-}
  [ -e "$host_path" ] || die "Plugin '${PLUGIN_NAME:-?}' wants to mount '$host_path', which does not exist."
  DOCKER_ARGS+=(-v "$host_path:$container_path${options:+:$options}")
}

# Cleanup a plugin wants run once `docker run` returns (normal exit, failure or Ctrl-C). A plain
# `trap ... EXIT` would replace whatever an earlier plugin registered, so collect them instead.
PLUGIN_EXIT_HOOKS=()
on_exit() { PLUGIN_EXIT_HOOKS+=("$1"); }
plugins_run_exit_hooks() {
  local hook
  for hook in ${PLUGIN_EXIT_HOOKS[@]+"${PLUGIN_EXIT_HOOKS[@]}"}; do eval "$hook"; done
}
trap plugins_run_exit_hooks EXIT

# --- helpers available to plugin web.sh scripts --------------------------------------------
#
# The web UI knows nothing about GitHub, branches or mirrors: it draws what the enabled plugins of
# a project describe here. WEB_JSON is that description, printed by `run.sh --web`.

WEB_JSON='{"lists":[],"notes":[],"session_items":[]}'

# The page has two places for what a plugin shows: a section of the project's band (web_list),
# and a session's own row, next to its VS Code button (web_session_item, web_tie_items). An item
# is {title, url} plus optional `ref` (a short id shown first, "#12"), `note` ("Draft"), `status`
# ("ok", "fail" or "pending", e.g. a pull request's CI) with its `status_text`, and anything a
# later plugin may want to read, such as the `branch` of a pull request. On a session's row it is
# a button opening `url` in a tab of its own, showing its status mark and `ref`.

# web_list <title> <json-array>: a section of links on the project's band. `start` ({label, task})
# puts a button on an item that starts a session with `task` as the agent's first message.
web_list() {
  WEB_JSON=$(jq -c --arg title "$1" --argjson items "$2" \
    '.lists += [{title: $title, items: $items}]' <<<"$WEB_JSON")
}

# web_session_item <run_id> <json-item>: an element on that run's session row, shown while the
# page lists a session of the run.
web_session_item() {
  WEB_JSON=$(jq -c --arg run_id "$1" --argjson item "$2" \
    '.session_items += [$item + {run_id: $run_id}]' <<<"$WEB_JSON")
}

# web_note <text>: one line shown with the project, for what kept a plugin from listing anything.
web_note() { WEB_JSON=$(jq -c --arg note "$1" '.notes += [$note]' <<<"$WEB_JSON"); }

# web_map_items <jq-filter>: rewrite every item listed so far, by plugins of a lower priority.
web_map_items() { WEB_JSON=$(jq -c ".lists[].items[] |= ($1)" <<<"$WEB_JSON"); }

# web_tie_items <jq-filter>: hand items listed so far to the run the filter names for each (a
# RUN_ID; null or "" leaves the item where it is). A tied item moves from its section to its
# run's session row while the page lists a session of that run; with none, it stays in its
# section with a Resume button.
web_tie_items() {
  WEB_JSON=$(jq -c ".lists[].items[] |= (. as \$i | (\$i | $1) as \$r
    | if (\$r // \"\") == \"\" then \$i else \$i + {run_id: \$r} end)" <<<"$WEB_JSON")
}

# web_checkout <glob>: where a run's /workspace is on this machine, `{run_id}` standing for the
# run. The page offers to open the directory it matches in VS Code.
web_checkout() { WEB_JSON=$(jq -c --arg glob "$1" '.checkout = $glob' <<<"$WEB_JSON"); }

# --- framework -----------------------------------------------------------------------------

plugins_discover() {
  command -v jq >/dev/null || die "jq is required on the host to read plugin manifests."
  [ -d "$PLUGIN_ROOT" ] || die "Plugin directory not found: $PLUGIN_ROOT"

  local files=() entries=() file dir name row i
  for dir in "$PLUGIN_ROOT"/*/; do
    [ -f "$dir/plugin.json" ] && files+=("$dir/plugin.json")
  done
  [ ${#files[@]} -gt 0 ] || die "No plugins found in $PLUGIN_ROOT"

  # One line per manifest, its fields split by the unit separator (not a tab: read would merge
  # the empty fields between two tabs).
  local rows
  if ! rows=$(jq -r '[(.priority // 50), (.defaultEnabled // false), (.requiredAgent // ""),
                      (.conflicts, .requiredEnv, .provides, .requires | . // [] | join(" "))]
                     | map(tostring) | join("\u001f")' "${files[@]}" 2>/dev/null); then
    for file in "${files[@]}"; do  # which one: jq read them all as one stream
      jq -e . "$file" >/dev/null 2>&1 || die "Malformed manifest: $file"
    done
    die "Could not read the plugin manifests in $PLUGIN_ROOT"
  fi
  mapfile -t rows <<<"$rows"
  [ ${#rows[@]} -eq ${#files[@]} ] || die "Could not read the plugin manifests in $PLUGIN_ROOT"

  for i in "${!files[@]}"; do
    name=$(basename "$(dirname "${files[$i]}")")
    IFS=$'\x1f' read -r -a row <<<"${rows[$i]}"
    local f
    for f in "${!PLUGIN_META_FIELDS[@]}"; do
      PLUGIN_META["$name ${PLUGIN_META_FIELDS[$f]}"]=${row[$f]-}
    done
    entries+=("$(plugin_meta "$name" priority) $name")
  done

  mapfile -t PLUGIN_LIST < <(printf '%s\n' "${entries[@]}" | sort -n -k1,1 -k2,2 | cut -d' ' -f2-)
}

plugins_resolve() {
  local name flag value source wanted
  ENABLED_PLUGINS=""
  for name in "${PLUGIN_LIST[@]}"; do
    flag=$(plugin_flag_name "$name")
    # The worked-on repo has the last word, then the ENABLE_ flag (already overlaid with the
    # project's own .env, see host-settings.sh), then the manifest default.
    value=$(project_plugin_setting "$name" '.enabled')
    source="$PROJECT_CONFIG_FILE (.plugins[\"$name\"].enabled)"
    if [ -z "$value" ]; then
      value="${!flag:-}"
      source="$flag"
    fi
    [ -n "$value" ] || { value=$(plugin_meta "$name" defaultEnabled); source="$name's manifest"; }
    case "$value" in
      1|true|yes|on)   ;;
      0|false|no|off)  continue ;;
      *) die "$source must be 0 or 1 (got: $value)" ;;
    esac
    # A plugin tied to one agent is silently dropped when another agent runs, rather than failing.
    wanted=$(plugin_meta "$name" requiredAgent)
    if [ -n "$wanted" ] && [ "$wanted" != "${AGENT:-claude}" ]; then
      continue
    fi
    ENABLED_PLUGINS="${ENABLED_PLUGINS:+$ENABLED_PLUGINS }$name"
  done
}

plugins_validate() {
  local name var cap other provided=" " providers

  for name in $ENABLED_PLUGINS; do
    for other in $(plugin_meta "$name" conflicts); do
      case " $ENABLED_PLUGINS " in
        *" $other "*) die "Plugins '$name' and '$other' cannot be enabled together. Disable one of them in .env or in the project's .claude-sandbox.json." ;;
      esac
    done
  done

  for name in $ENABLED_PLUGINS; do
    for var in $(plugin_meta "$name" requiredEnv); do
      [ -n "${!var:-}" ] || die "Plugin '$name' requires $var to be set in .env or in the project's .claude-sandbox.json"
    done
    provided+="$(plugin_meta "$name" provides) "
  done

  for name in $ENABLED_PLUGINS; do
    for cap in $(plugin_meta "$name" requires); do
      case "$provided" in
        *" $cap "*) ;;
        *)
          providers=$(plugin_providers_of "$cap" | paste -sd, -)
          die "Plugin '$name' requires the '$cap' capability. Enable one of: ${providers:-<none available>}" ;;
      esac
    done
  done
}

# Source each enabled plugin's host.sh so it can validate its config and contribute docker args.
plugins_host_stage() {
  local name
  for name in $ENABLED_PLUGINS; do
    PLUGIN_NAME="$name"
    PLUGIN_DIR="$PLUGIN_ROOT/$name"
    if [ -f "$PLUGIN_DIR/host.sh" ]; then
      # shellcheck disable=SC1091  # path resolved at runtime
      . "$PLUGIN_DIR/host.sh"
    fi
  done
  unset PLUGIN_NAME PLUGIN_DIR
}

# Source each enabled plugin's web.sh, in priority order, so it can describe its part of the page.
plugins_web_stage() {
  local name
  for name in $ENABLED_PLUGINS; do
    PLUGIN_NAME="$name"
    PLUGIN_DIR="$PLUGIN_ROOT/$name"
    if [ -f "$PLUGIN_DIR/web.sh" ]; then
      # shellcheck disable=SC1091  # path resolved at runtime
      . "$PLUGIN_DIR/web.sh"
    fi
  done
  unset PLUGIN_NAME PLUGIN_DIR
}
