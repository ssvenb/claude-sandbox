# shellcheck shell=bash
# Host-side plugin framework: what a plugin's host.sh and web.sh are sourced with. Sourced by
# src/contract/host/stage.sh (bash, on YOUR machine), which run.sh's Python side (src/orchestrator) starts once
# it has resolved which plugins run.
#
# A plugin is a directory under plugins/ with a plugin.json manifest and optional lifecycle
# scripts, one per privilege stage:
#   host.sh        sourced here, on the host — validates config, appends to DOCKER_ARGS
#   web.sh         sourced here, on the host, by `run.sh --web` — what the web UI shows for a project
#   root-init.sh   sourced by entrypoint.sh as root: setup that needs root, not a boundary
#   agent-init.sh  sourced by agent-setup.sh as the unprivileged 'node' user
#
# Enablement is resolved ONCE, by src/orchestrator/plugins.py, and handed to the stages and the container
# as $ENABLED_PLUGINS, so neither re-interprets the ENABLE_* flags.

PLUGIN_ROOT="${PLUGIN_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)/plugins}"

# Every flag the plugins want on the `docker run` command line.
DOCKER_ARGS=()
# Every --build-arg the plugins want on the `docker build` command line.
BUILD_ARGS=()
# Space-separated, priority-ordered names of the plugins that run, as src/orchestrator resolved them.
ENABLED_PLUGINS="${ENABLED_PLUGINS:-}"

die() { echo "❌ $*" >&2; exit 1; }

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
# The web UI knows nothing about any plugin: it draws what the enabled plugins of a project
# describe here, and the page code they bring themselves (web_command, web_server). WEB_JSON is that description, printed by `run.sh --web`.

WEB_JSON='{"lists":[],"notes":[],"session_items":[],"run_items":[],"live":[],"commands":{},"servers":{},"starts":[]}'

# The page has two places for what a plugin shows: a section of the project's band (web_list),
# and a session's own row (web_session_item, web_run_items,
# web_tie_items). An item is {title, url} plus optional `ref` (a short id shown first, "#12"),
# `note` ("Draft"), `status` ("ok", "fail" or "pending", e.g. a pull request's CI; "done",
# e.g. a merged one) with its `status_text`, and anything a later plugin may want to read, such as the `branch` of a pull
# request. On a session's row it is a button opening `url` in a tab of its own, showing its status
# mark and `ref`.
#
# `on_delete` ({ask, action, arg}) offers to tidy an item up when its run's session is deleted:
# the page asks `ask` (a yes/no question, "Close pull request #12?"), and only on a yes runs
# `run.sh --web-action <plugin> <action> <arg>`, which sources the listing plugin's web.sh with
# WEB_ACTION and WEB_ACTION_ARG set (see plugins_web_action). The listing helpers stamp the
# plugin's name into it.

# _web_items <json-array>: the items, each `on_delete` stamped with the plugin that listed it.
_web_items() {
  jq -c --arg plugin "${PLUGIN_NAME:-}" 'map(if .on_delete then .on_delete.plugin = $plugin else . end)' <<<"$1"
}

# web_list <title> <json-array>: a section of links on the project's band. `start` ({label, task})
# puts a button on an item that starts a session with `task` as the agent's first message.
web_list() {
  WEB_JSON=$(jq -c --arg title "$1" --argjson items "$(_web_items "$2")" \
    '.lists += [{title: $title, items: $items}]' <<<"$WEB_JSON")
}

# web_run_items <json-array>: items that show only for a run: once a later plugin ties one to a
# run (web_tie_items), on the row of that run's session while the page lists one. With no session
# of the run listed, an item naming a `section` ("Pull requests": a run's open one) shows under
# that title on the project's panel, with a Resume button; any other, nowhere. Never untied.
web_run_items() {
  WEB_JSON=$(jq -c --argjson items "$(_web_items "$1")" '.run_items += $items' <<<"$WEB_JSON")
}

# web_session_item <run_id> <json-item>: an element on that run's session row, shown while the
# page lists a session of the run.
web_session_item() {
  WEB_JSON=$(jq -c --arg run_id "$1" --argjson item "$(_web_items "[$2]")" \
    '.session_items += [$item[0] + {run_id: $run_id}]' <<<"$WEB_JSON")
}

# web_live_items <file>: a JSON array of items, each with its `run_id`, that the web server re-reads
# on every poll of the page and puts on the row of that run's running session — for what comes and
# goes within seconds (a port a session's server publishes), where waiting for the project to be
# described again would not do. A `url` may say `{host}` for the name the page was opened by. The
# file need not exist yet.
web_live_items() { WEB_JSON=$(jq -c --arg file "$1" '.live += [$file]' <<<"$WEB_JSON"); }

# web_poll <seconds>: has the web server describe the project again at least this often, with or
# without a page open — for what a plugin watches (a pull request's CI) rather than merely shows.
# The shortest interval any plugin of the project asked for counts; the server allows no less
# than 10 seconds.
web_poll() {
  [[ $1 =~ ^[0-9]+$ ]] || die "Plugin '${PLUGIN_NAME:-?}': web_poll takes seconds, got '$1'."
  WEB_JSON=$(jq -c --argjson s "$1" '.poll = ([.poll // $s, $s] | min)' <<<"$WEB_JSON")
}

# web_start <json>: a session the web server starts by itself, unattended: {key, task} plus
# optional `env` ({NAME: VALUE}: sandbox settings for that run alone, as `run.sh --set`) and
# `after_run` (a RUN_ID: not while the page lists a session of that run — its work is not over).
# `task` is the agent's first message. Started once per `key` of the plugin in the project,
# however often it is described, and removed again as soon as its agent has finished (one that
# asks something stays, waiting on the dashboard). In its stages SANDBOX_STARTED_BY names the plugin.
web_start() {
  WEB_JSON=$(jq -c --arg plugin "$PLUGIN_NAME" --argjson start "$1" '.starts += [$start + {plugin: $plugin}]' <<<"$WEB_JSON")
}

# web_on_status <command> [args…]: what the web server runs, on this machine, each time the status
# of one of the project's sessions changes as the page shows it (idle with background tasks running
# is working), with {project, run_id, session, url, status, before} as JSON on stdin: `url` is the
# session's page, `status` and `before` are starting, working, idle, question, or null once it ended.
web_on_status() {
  WEB_JSON=$(jq -c --arg plugin "$PLUGIN_NAME" '.on_status[$plugin] = $ARGS.positional' --args "$@" <<<"$WEB_JSON")
}

# web_note <text>: one line shown with the project, for what kept a plugin from listing anything.
web_note() { WEB_JSON=$(jq -c --arg note "$1" '.notes += [$note]' <<<"$WEB_JSON"); }

# web_map_items <jq-filter>: rewrite every item listed so far, by plugins of a lower priority.
web_map_items() { WEB_JSON=$(jq -c "(.lists[].items[], .run_items[]) |= ($1)" <<<"$WEB_JSON"); }

# web_tie_items <jq-filter>: hand items listed so far to the run the filter names for each (a
# RUN_ID; null or "" leaves the item where it is). A tied item of a section moves from it to its
# run's session row while the page lists a session of that run; with none, it stays in its
# section with a Resume button. A tied run item (web_run_items) shows on that row, or with no
# session listed under the `section` it names, if any.
web_tie_items() {
  WEB_JSON=$(jq -c "(.lists[].items[], .run_items[]) |= (. as \$i | (\$i | $1) as \$r
    | if (\$r // \"\") == \"\" then \$i else \$i + {run_id: \$r} end)" <<<"$WEB_JSON")
}

# web_action_done: in a web action (WEB_ACTION set), says the plugin did it. Without it the action
# failed, the first web_note saying why.
web_action_done() { WEB_ACTION_DONE=1; }

# web_checkout <glob>: where a run's /workspace is on this machine, `{run_id}` standing for the
# run: a session's `workspace`, where web_command runs.
web_checkout() { WEB_JSON=$(jq -c --arg glob "$1" '.checkout = $glob' <<<"$WEB_JSON"); }

# A plugin draws its own part of the page in plugins/<name>/web/index.tsx (see web/src/plugins.ts),
# and asks the web server for what it needs through these two.

# web_command <name> <command> [args…]: what the web server runs in a run's checkout (web_checkout)
# when the plugin's page code asks (GET /api/sessions/<id>/plugins/<plugin>/<name>): the JSON it
# prints is the answer.
web_command() {
  WEB_JSON=$(jq -c --arg plugin "$PLUGIN_NAME" --arg name "$1" '.commands[$plugin][$name] = $ARGS.positional' \
    --args "${@:2}" <<<"$WEB_JSON")
}

# web_server <command> [args…]: an HTTP server of the plugin's, which the web server starts on the
# first request under /plugins/<plugin>/ and passes every such request to, behind its own guard.
# One for all projects. It listens on the unix socket WEB_SOCKET names, its paths under WEB_BASE.
web_server() {
  WEB_JSON=$(jq -c --arg plugin "$PLUGIN_NAME" '.servers[$plugin] = $ARGS.positional' --args "$@" <<<"$WEB_JSON")
}

# --- framework -----------------------------------------------------------------------------

# Source each enabled plugin's host.sh so it can validate its config and contribute docker args.
# Which of DOCKER_ARGS each one added is kept, for plugin_docker_args.
declare -A PLUGIN_ARGS_FROM=() PLUGIN_ARGS_TO=()
plugins_host_stage() {
  # A name no host.sh uses: they are sourced into this function, and may set any other.
  local _plugins_host_name
  for _plugins_host_name in $ENABLED_PLUGINS; do
    PLUGIN_NAME="$_plugins_host_name"
    PLUGIN_DIR="$PLUGIN_ROOT/$_plugins_host_name"
    PLUGIN_ARGS_FROM[$_plugins_host_name]=${#DOCKER_ARGS[@]}
    if [ -f "$PLUGIN_DIR/host.sh" ]; then
      # shellcheck disable=SC1091  # path resolved at runtime
      . "$PLUGIN_DIR/host.sh"
    fi
    PLUGIN_ARGS_TO[$_plugins_host_name]=${#DOCKER_ARGS[@]}
  done
  unset PLUGIN_NAME PLUGIN_DIR
}

# A container of the run's own beside the sandbox (dev-server's demo container) may take what some
# plugins hand the sandbox, without either knowing the other: a plugin whose manifest says
# "sibling": true declares its `docker run` args and its container stages fit any such container
# (a proxy's sockets, certificates, Sysbox), and the sibling's owner may add others it was told to.

# plugin_siblings: the enabled plugins that declare "sibling": true and whose host stage ran already.
plugin_siblings() {
  local name
  for name in $ENABLED_PLUGINS; do
    [ -n "${PLUGIN_ARGS_TO[$name]:-}" ] && jq -e '.sibling == true' "$PLUGIN_ROOT/$name/plugin.json" >/dev/null \
      && printf '%s\n' "$name"
  done
  return 0
}

# plugin_docker_args <plugin>...: the `docker run` args those plugins' host stages added, into
# PLUGIN_DOCKER_ARGS. Only a plugin whose host stage ran already (an enabled one of a lower priority).
plugin_docker_args() {
  local name
  PLUGIN_DOCKER_ARGS=()
  for name in "$@"; do
    [ -n "${PLUGIN_ARGS_TO[$name]:-}" ] \
      || die "Plugin '${PLUGIN_NAME:-?}' wants what '$name' hands the sandbox, but '$name' is not enabled or comes after it."
    PLUGIN_DOCKER_ARGS+=(${DOCKER_ARGS[@]+"${DOCKER_ARGS[@]:${PLUGIN_ARGS_FROM[$name]}:$((PLUGIN_ARGS_TO[$name] - PLUGIN_ARGS_FROM[$name]))}"})
  done
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

# plugins_web_action <plugin> <action> <arg>: what the page asked for when a session was deleted
# (an item's `on_delete`, after a yes): sources that plugin's web.sh alone, with WEB_ACTION and
# WEB_ACTION_ARG set, and fails unless it called web_action_done.
plugins_web_action() {
  case " $ENABLED_PLUGINS " in
    *" $1 "*) ;;
    *) die "Plugin '$1' is not enabled for this project." ;;
  esac
  PLUGIN_NAME="$1"
  PLUGIN_DIR="$PLUGIN_ROOT/$1"
  [ -f "$PLUGIN_DIR/web.sh" ] || die "Plugin '$1' has no web.sh."
  # shellcheck disable=SC2034  # read by the plugin's web.sh
  WEB_ACTION="$2" WEB_ACTION_ARG="$3" WEB_ACTION_DONE=0
  # shellcheck disable=SC1091  # path resolved at runtime
  . "$PLUGIN_DIR/web.sh" || true
  unset PLUGIN_NAME PLUGIN_DIR WEB_ACTION WEB_ACTION_ARG
  [ "$WEB_ACTION_DONE" = 1 ] ||
    die "$(jq -r '.notes[0] // empty' <<<"$WEB_JSON" | grep . || echo "$1 did not do '$2'")"
}
