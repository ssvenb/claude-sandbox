#!/bin/bash
# Build and launch a coding-agent sandbox container. Runs on YOUR machine, where any long-lived
# credentials stay; the container only ever receives what the agent and the enabled plugins
# hand it.
#
# Configuration comes from .env next to this script. The core needs only:
#   AGENT                   which CLI agent runs (agents/*, default: claude)
# plus whatever credentials that agent asks for — see agents/*/host.sh. Everything else belongs
# to a plugin — see plugins/*/plugin.json and .env.example. Plugins are switched with
# ENABLE_<PLUGIN_NAME> flags, e.g. ENABLE_GITHUB_AUTH=0.
set -euo pipefail

cd "$(dirname "$0")"
# Export everything sourced so plugins and the container inherit it.
set -a
# shellcheck disable=SC1091
[ -f .env ] && source .env
set +a

# shellcheck source=src/lib/host-plugins.sh
. src/lib/host-plugins.sh
# shellcheck source=src/lib/host-agents.sh
. src/lib/host-agents.sh

# --resume <RUN_ID>: re-attach to that run. No arg → fresh run.
usage() { echo "Usage: $0 [--resume <RUN_ID>]   (RUN_ID is 6 hex chars)" >&2; exit "${1:-1}"; }
RESUME=0
RUN_ID=""
while [ $# -gt 0 ]; do
  case "$1" in
    --resume) RESUME=1; RUN_ID="${2:-}"; shift 2 || true ;;
    -h|--help) usage 0 ;;
    *) echo "Unknown argument: $1" >&2; usage ;;
  esac
done
if [ "$RESUME" = 1 ]; then
  case "$RUN_ID" in
    [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
    *) echo "Invalid RUN_ID '$RUN_ID' (expected 6 lowercase hex chars)." >&2; usage ;;
  esac
fi

# Pick the agent first: plugins that declare a different requiredAgent are dropped from the run.
agent_resolve

# Work out which plugins run, fail fast on unmet config/capabilities, then let each one
# contribute its own docker run arguments. The agent's host stage comes last, so a plugin that
# brings credentials of its own (AGENT_AUTH_PROVIDED=1) is already accounted for.
plugins_discover
plugins_resolve
plugins_validate
plugins_host_stage
agent_host_stage
echo "🤖 Agent: $AGENT"
echo "🔌 Plugins: ${ENABLED_PLUGINS:-<none>}"

# One id keys the run; a plugin may derive a branch name from it. Fresh run mints one;
# --resume reuses it.
[ "$RESUME" = 1 ] || RUN_ID=$(openssl rand -hex 3)   # 6 lowercase hex chars, DNS-safe

# Agent and plugin mix are baked in: only the selected agent's and the enabled plugins'
# install.sh run, so changing either rebuilds. Each agent gets its own image tag.
IMAGE="claude-agent:$AGENT"
docker build -t "$IMAGE" \
  --build-arg AGENT="$AGENT" \
  --build-arg ENABLED_PLUGINS="$ENABLED_PLUGINS" .

docker run -it --rm \
  -e RUN_ID="$RUN_ID" \
  -e RESUME="$RESUME" \
  -e AGENT="$AGENT" \
  -e ENABLED_PLUGINS="$ENABLED_PLUGINS" \
  ${DOCKER_ARGS[@]+"${DOCKER_ARGS[@]}"} \
  "$IMAGE"
