#!/bin/bash
# Build and launch a Claude sandbox container. Runs on YOUR machine, which holds the GitHub App
# private key; the container only ever sees short-lived installation tokens minted from it.
#
# Configuration comes from .env next to this script:
#   GH_APP_ID            GitHub App id
#   GH_PRIVATE_KEY_FILE  path to the App's .pem private key
#   REPO_URL             https clone URL of the repo the agent works on
#   BASE_BRANCH          branch new agent branches are cut from (default: main)
#   CLAUDE_CODE_OAUTH_TOKEN
set -euo pipefail

cd "$(dirname "$0")"
# Export everything sourced so the container inherits the OAuth/GitHub App settings.
set -a
# shellcheck disable=SC1091
[ -f .env ] && source .env
set +a

# --resume <RUN_ID>: re-attach to that run's branch. No arg → fresh run.
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

: "${GH_APP_ID:?GH_APP_ID must be set in .env}"
: "${GH_PRIVATE_KEY_FILE:?GH_PRIVATE_KEY_FILE must point at the GitHub App .pem in .env}"
: "${REPO_URL:?REPO_URL must be set in .env (https clone URL)}"
: "${CLAUDE_CODE_OAUTH_TOKEN:?CLAUDE_CODE_OAUTH_TOKEN must be set in .env}"
BASE_BRANCH="${BASE_BRANCH:-main}"

# One id keys the run's git branch. Fresh run mints one; --resume reuses it.
[ "$RESUME" = 1 ] || RUN_ID=$(openssl rand -hex 3)   # 6 lowercase hex chars, DNS-safe

docker build -t claude-agent .

docker run -it --rm \
  -e RUN_ID="$RUN_ID" \
  -e RESUME="$RESUME" \
  -e REPO_URL="$REPO_URL" \
  -e BASE_BRANCH="$BASE_BRANCH" \
  -e CLAUDE_CODE_OAUTH_TOKEN="$CLAUDE_CODE_OAUTH_TOKEN" \
  -e GH_APP_ID="$GH_APP_ID" \
  -e GH_PRIVATE_KEY="$(cat "$GH_PRIVATE_KEY_FILE")" \
  claude-agent
