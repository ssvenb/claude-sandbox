#!/bin/bash
# Build and launch a coding-agent sandbox container. Runs on YOUR machine, where the long-lived
# credentials stay; the container only ever receives what the agent and the enabled plugins hand
# it. Configuration lives in .env; the repo you launch from can override any of it (.env,
# .claude-sandbox.json — see src/lib/host-settings.sh).
set -euo pipefail

# The directory you launched from is the repo the agent works on — plugins read it as $HOST_CWD,
# never as $PWD.
export HOST_CWD="$PWD"
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
# shellcheck source=src/lib/host-project-config.sh
. src/lib/host-project-config.sh
# shellcheck source=src/lib/host-project-env.sh
. src/lib/host-project-env.sh
# shellcheck source=src/lib/host-settings.sh
. src/lib/host-settings.sh

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
plugins_validate
plugins_host_stage
agent_host_stage
echo "🤖 Agent: $AGENT"
echo "🔌 Plugins: ${ENABLED_PLUGINS:-<none>}"

# One id keys the run; --resume reuses it. 6 lowercase hex chars, DNS-safe.
[ "$RESUME" = 1 ] || RUN_ID=$(openssl rand -hex 3)

# Agent, plugin mix and CLI version are all build args, so the image rebuilds exactly when one of
# them changes and is fully cached otherwise.
IMAGE="claude-agent:$AGENT"
agent_version_resolve
docker build -t "$IMAGE" \
  --build-arg AGENT="$AGENT" \
  --build-arg AGENT_VERSION="${AGENT_VERSION:-}" \
  --build-arg ENABLED_PLUGINS="$ENABLED_PLUGINS" .

docker run -it --rm \
  -e RUN_ID="$RUN_ID" \
  -e RESUME="$RESUME" \
  -e AGENT="$AGENT" \
  -e ENABLED_PLUGINS="$ENABLED_PLUGINS" \
  ${DOCKER_ARGS[@]+"${DOCKER_ARGS[@]}"} \
  "$IMAGE"
