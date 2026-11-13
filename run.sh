#!/bin/bash
# Build and launch a coding-agent sandbox container. Runs on YOUR machine, where the long-lived
# credentials stay; the container only ever receives what the agent and the enabled plugins hand
# it. Configuration is project-specific: it comes from the repo you launch from (.env,
# .claude-sandbox.json — see src/lib/host-settings.sh), never from the sandbox's own directory.
set -euo pipefail

# The directory you launched from is the repo the agent works on — plugins read it as $HOST_CWD,
# never as $PWD.
export HOST_CWD="$PWD"
cd "$(dirname "$0")"

# shellcheck source=src/lib/host-plugins.sh
. src/lib/host-plugins.sh
# shellcheck source=src/lib/host-credentials.sh
. src/lib/host-credentials.sh
# shellcheck source=src/lib/host-agents.sh
. src/lib/host-agents.sh
# shellcheck source=src/lib/host-project-config.sh
. src/lib/host-project-config.sh
# shellcheck source=src/lib/host-project-env.sh
. src/lib/host-project-env.sh
# shellcheck source=src/lib/host-settings.sh
. src/lib/host-settings.sh
# shellcheck source=src/lib/host-ports.sh
. src/lib/host-ports.sh

usage() { echo "Usage: $0 [--resume <RUN_ID> | --run-id <RUN_ID> | --web | --web-action <PLUGIN> <ACTION> <ARG>] [--task TEXT] [--chat]   (RUN_ID is 6 hex chars)" >&2; exit "${1:-1}"; }
RESUME=0
WEB=0
WEB_ACTION_ARGS=()
TASK=""
CHAT=0
GIVEN_ID=0
RUN_ID=""
while [ $# -gt 0 ]; do
  case "$1" in
    # --run-id starts a FRESH run under an id the caller picked (web/server.py does, to know which
    # run a session is before the container says so); --resume re-attaches to an existing one.
    --resume|--run-id) [ "$1" = --run-id ] || RESUME=1
      GIVEN_ID=1; RUN_ID="${2:-}"; shift; [ $# -eq 0 ] || shift ;;
    # Starts nothing: prints, as JSON, what the project's enabled plugins have for the web UI.
    --web) WEB=1; shift ;;
    # Starts nothing either: does what an item's `on_delete` names, once the web UI's user said
    # yes to it (closing a deleted session's pull request).
    --web-action) [ $# -ge 4 ] || { echo "--web-action needs a plugin, an action and its argument." >&2; usage; }
      WEB=2; WEB_ACTION_ARGS=("$2" "$3" "$4"); shift 4 ;;
    # The agent's first message, so it starts working without anyone typing (the web UI's Resolve).
    --task) TASK="${2:-}"; shift; [ $# -eq 0 ] || shift
      [ -n "$TASK" ] || { echo "--task needs the task's text." >&2; usage; } ;;
    # No terminal: the agent runs behind its chat bridge (agents/<name>/chat.mjs) and this
    # process's stdin and stdout carry the chat's commands and events (src/lib/chat-bridge.mjs).
    # What the web UI starts; prompts arrive as commands, so there is no --task with it.
    --chat) CHAT=1; shift ;;
    -h|--help) usage 0 ;;
    *) echo "Unknown argument: $1" >&2; usage ;;
  esac
done
[ -z "$TASK" ] || [ "$CHAT" = 0 ] || { echo "--chat takes its prompts as commands; it has no --task." >&2; usage; }
[ -z "$TASK" ] || [ "$RESUME" = 0 ] || { echo "--task starts a fresh run; it cannot resume one." >&2; usage; }
if [ "$GIVEN_ID" = 1 ]; then
  case "$RUN_ID" in
    [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
    *) echo "Invalid RUN_ID '$RUN_ID' (expected 6 lowercase hex chars)." >&2; usage ;;
  esac
fi

# One id and date key the run; --resume and --run-id bring their own. 6 lowercase hex chars, DNS-safe. Both are
# core so any plugin's host stage can name its per-run artifacts the same way.
[ "$GIVEN_ID" = 1 ] || RUN_ID=$(openssl rand -hex 3)
RUN_DATE=$(date -u +%Y%m%d)
export RUN_ID RUN_DATE

# --web answers with one JSON document on stdout, so everything else said on the way goes to stderr.
[ "$WEB" = 0 ] || exec 3>&1 >&2

# The worked-on repo's own files overlay .env before anything reads it, so even AGENT and the
# plugin mix are per-project.
project_config_load
project_env_load
project_settings_apply

# Agent first: plugins declaring a different requiredAgent are dropped from the run.
agent_resolve

# The agent's host stage comes last, so a plugin bringing credentials of its own
# (AGENT_AUTH_PROVIDED=1) is already accounted for.
plugins_discover
plugins_resolve
if [ "$WEB" = 2 ]; then
  plugins_web_action "${WEB_ACTION_ARGS[@]}"
  echo '{}' >&3
  exit 0
fi
if [ "$WEB" = 1 ]; then
  # Resolved exactly as a run would be, but not validated: a project that cannot start yet (no
  # App key, say) still has pull requests to show.
  plugins_web_stage
  ports_web
  jq -c --arg agent "$AGENT" --arg plugins "$ENABLED_PLUGINS" \
    '. + {agent: $agent, plugins: ($plugins | split(" "))}' <<<"$WEB_JSON" >&3
  exit 0
fi
[ "$CHAT" = 0 ] || [ -f "agents/$AGENT/chat.mjs" ] \
  || { echo "❌ The $AGENT agent has no chat bridge (agents/$AGENT/chat.mjs): start it without --chat." >&2; exit 1; }
plugins_validate
plugins_host_stage
agent_host_stage
# After every host stage, so a credential may depend on what any of them set up.
credentials_start
# Whatever the agent serves reaches you through the central port proxy (src/lib/host-ports.sh).
ports_start
echo "🤖 Agent: $AGENT"
echo "🔌 Plugins: ${ENABLED_PLUGINS:-<none>}"

# Agent, plugin mix and CLI version are all build args, so the image rebuilds exactly when one of
# them changes and is fully cached otherwise.
IMAGE="claude-agent:$AGENT"
agent_version_resolve
docker build -t "$IMAGE" \
  --build-arg AGENT="$AGENT" \
  --build-arg AGENT_VERSION="${AGENT_VERSION:-}" \
  --build-arg ENABLED_PLUGINS="$ENABLED_PLUGINS" \
  ${BUILD_ARGS[@]+"${BUILD_ARGS[@]}"} .

# A chat has no terminal to attach: its stdio is the bridge's wire, which a pty would mangle.
[ "$CHAT" = 1 ] && TTY=(-i -e AGENT_UI=chat) || TTY=(-it)
docker run "${TTY[@]}" --rm \
  -e RUN_ID="$RUN_ID" \
  -e RUN_DATE="$RUN_DATE" \
  -e RESUME="$RESUME" \
  -e AGENT="$AGENT" \
  -e ENABLED_PLUGINS="$ENABLED_PLUGINS" \
  ${TASK:+-e "AGENT_TASK=$TASK"} \
  ${DOCKER_ARGS[@]+"${DOCKER_ARGS[@]}"} \
  --name "sandbox-$RUN_ID" \
  "$IMAGE"
