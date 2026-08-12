#!/bin/bash
# Build and launch a Claude sandbox container. Runs on YOUR machine, where any long-lived
# credentials stay; the container only ever receives what the enabled plugins hand it.
#
# Configuration comes from .env next to this script. The core needs only:
#   CLAUDE_CODE_OAUTH_TOKEN (unless the claude-home plugin mounts a ~/.claude that has creds)
# Everything else belongs to a plugin — see plugins/*/plugin.json and .env.example. Plugins are
# switched with ENABLE_<PLUGIN_NAME> flags, e.g. ENABLE_GITHUB_AUTH=0.
set -euo pipefail

cd "$(dirname "$0")"
# Export everything sourced so plugins and the container inherit it.
set -a
# shellcheck disable=SC1091
[ -f .env ] && source .env
set +a

# shellcheck source=src/lib/host-plugins.sh
. src/lib/host-plugins.sh

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

# Work out which plugins run, fail fast on unmet config/capabilities, then let each one
# contribute its own docker run arguments.
plugins_discover
plugins_resolve
plugins_validate
plugins_host_stage
echo "🔌 Plugins: ${ENABLED_PLUGINS:-<none>}"

# A plugin that supplies Claude credentials itself sets CLAUDE_AUTH_PROVIDED during its host stage.
[ "${CLAUDE_AUTH_PROVIDED:-0}" = 1 ] \
  || : "${CLAUDE_CODE_OAUTH_TOKEN:?CLAUDE_CODE_OAUTH_TOKEN must be set in .env}"

# One id keys the run; a plugin may derive a branch name from it. Fresh run mints one;
# --resume reuses it.
[ "$RESUME" = 1 ] || RUN_ID=$(openssl rand -hex 3)   # 6 lowercase hex chars, DNS-safe

# The plugin mix is baked in: only enabled plugins' install.sh run, so toggling a flag rebuilds.
docker build -t claude-agent --build-arg ENABLED_PLUGINS="$ENABLED_PLUGINS" .

docker run -it --rm \
  -e RUN_ID="$RUN_ID" \
  -e RESUME="$RESUME" \
  -e ENABLED_PLUGINS="$ENABLED_PLUGINS" \
  ${CLAUDE_CODE_OAUTH_TOKEN:+-e CLAUDE_CODE_OAUTH_TOKEN="$CLAUDE_CODE_OAUTH_TOKEN"} \
  ${DOCKER_ARGS[@]+"${DOCKER_ARGS[@]}"} \
  claude-agent
