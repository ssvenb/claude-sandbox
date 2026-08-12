# shellcheck shell=bash
# Host-side plugin framework. Sourced by run.sh (bash, on YOUR machine).
#
# A plugin is a directory under plugins/ with a plugin.json manifest and optional lifecycle
# scripts, one per privilege stage:
#   host.sh        sourced here, on the host — validates config, appends to DOCKER_ARGS
#   root-init.sh   sourced by entrypoint.sh as root, where secrets live
#   agent-init.sh  sourced by agent-setup.sh as the unprivileged 'node' user
#
# Enablement is resolved ONCE here and handed to the container as $ENABLED_PLUGINS, so the
# container never re-interprets the ENABLE_* flags.

PLUGIN_ROOT="${PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/plugins}"

# Every -e/-v flag the plugins want on the `docker run` command line.
DOCKER_ARGS=()
# Space-separated, priority-ordered names of the plugins that will actually run.
ENABLED_PLUGINS=""
# Priority-ordered names of every plugin found on disk.
PLUGIN_LIST=()

die() { echo "❌ $*" >&2; exit 1; }

# ENABLE_ flag for a plugin: github-auth → ENABLE_GITHUB_AUTH.
plugin_flag_name() { printf 'ENABLE_%s' "$(printf '%s' "$1" | tr 'a-z-' 'A-Z_')"; }

plugin_meta() { jq -r "$2" "$PLUGIN_ROOT/$1/plugin.json"; }

# Names of the plugins (enabled or not) that advertise a given capability.
plugin_providers_of() {
  local p
  for p in "${PLUGIN_LIST[@]}"; do
    if jq -e --arg c "$1" '(.provides // []) | index($c)' \
         "$PLUGIN_ROOT/$p/plugin.json" >/dev/null 2>&1; then
      echo "$p"
    fi
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

# Mount a host path into the container: pass_mount <host-path> <container-path> [options]
pass_mount() {
  local host_path=$1 container_path=$2 options=${3:-}
  [ -e "$host_path" ] || die "Plugin '${PLUGIN_NAME:-?}' wants to mount '$host_path', which does not exist."
  DOCKER_ARGS+=(-v "$host_path:$container_path${options:+:$options}")
}

# --- framework -----------------------------------------------------------------------------

plugins_discover() {
  command -v jq >/dev/null || die "jq is required on the host to read plugin manifests."
  [ -d "$PLUGIN_ROOT" ] || die "Plugin directory not found: $PLUGIN_ROOT"

  local entries=() dir name
  for dir in "$PLUGIN_ROOT"/*/; do
    [ -f "$dir/plugin.json" ] || continue
    name=$(basename "$dir")
    jq -e . "$dir/plugin.json" >/dev/null 2>&1 || die "Malformed manifest: $dir/plugin.json"
    entries+=("$(plugin_meta "$name" '.priority // 50') $name")
  done
  [ ${#entries[@]} -gt 0 ] || die "No plugins found in $PLUGIN_ROOT"

  mapfile -t PLUGIN_LIST < <(printf '%s\n' "${entries[@]}" | sort -n -k1,1 -k2,2 | cut -d' ' -f2-)
}

plugins_resolve() {
  local name flag value wanted
  ENABLED_PLUGINS=""
  for name in "${PLUGIN_LIST[@]}"; do
    flag=$(plugin_flag_name "$name")
    # Unset flag falls back to the manifest default, so existing .env files keep working.
    value="${!flag:-$(plugin_meta "$name" '.defaultEnabled // false')}"
    case "$value" in
      1|true|yes|on)   ;;
      0|false|no|off)  continue ;;
      *) die "$flag must be 0 or 1 (got: $value)" ;;
    esac
    # A plugin tied to one agent (Claude-shaped hooks, a wrapper around `claude`, …) is silently
    # dropped when another agent runs, instead of failing the run.
    wanted=$(plugin_meta "$name" '.requiredAgent // empty')
    if [ -n "$wanted" ] && [ "$wanted" != "${AGENT:-claude}" ]; then
      echo "⏭️  Plugin '$name' skipped: it requires agent '$wanted', this run uses '${AGENT:-claude}'."
      continue
    fi
    ENABLED_PLUGINS="${ENABLED_PLUGINS:+$ENABLED_PLUGINS }$name"
  done
}

plugins_validate() {
  local name var cap other provided=" " providers

  for name in $ENABLED_PLUGINS; do
    while read -r other; do
      [ -n "$other" ] || continue
      case " $ENABLED_PLUGINS " in
        *" $other "*) die "Plugins '$name' and '$other' cannot be enabled together. Disable one of them in .env." ;;
      esac
    done < <(plugin_meta "$name" '.conflicts // [] | .[]')
  done

  for name in $ENABLED_PLUGINS; do
    while read -r var; do
      [ -n "$var" ] || continue
      [ -n "${!var:-}" ] || die "Plugin '$name' requires $var to be set in .env"
    done < <(plugin_meta "$name" '.requiredEnv // [] | .[]')
    provided+="$(plugin_meta "$name" '.provides // [] | join(" ")') "
  done

  for name in $ENABLED_PLUGINS; do
    while read -r cap; do
      [ -n "$cap" ] || continue
      case "$provided" in
        *" $cap "*) ;;
        *)
          providers=$(plugin_providers_of "$cap" | paste -sd, -)
          die "Plugin '$name' requires the '$cap' capability. Enable one of: ${providers:-<none available>}" ;;
      esac
    done < <(plugin_meta "$name" '.requires // [] | .[]')
  done
}

# Source each enabled plugin's host.sh so it can validate its own config and contribute
# docker run arguments.
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
