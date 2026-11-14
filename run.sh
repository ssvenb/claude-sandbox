#!/bin/sh
# Build and launch a coding-agent sandbox container. Runs on YOUR machine, where the long-lived
# credentials stay; the container only ever receives what the agent and the enabled plugins hand it.
#
#   run.sh [--resume <RUN_ID> | --run-id <RUN_ID> | --web | --web-action <PLUGIN> <ACTION> <ARG>]
#          [--task TEXT] [--chat]
#
# The work is src/orchestrator (Python); the plugins' and the agent's host.sh and web.sh are bash,
# sourced by src/contract/host/stage.sh. It runs in this checkout's uv environment (.venv, which
# ./install.sh creates, and the first run does if it is missing) — exec'd directly rather than
# through `uv run`, so the run is this one process: its pid, its signals, its exit status.
# readlink: install.sh links this file into ~/.local/bin as `claude-sandbox`.
here=$(dirname "$(readlink -f "$0")")
if [ ! -x "$here/.venv/bin/python" ]; then
  command -v uv >/dev/null || { echo "❌ uv is required (https://docs.astral.sh/uv/): run $here/install.sh" >&2; exit 1; }
  uv sync --project "$here" --frozen --no-dev >&2 || exit 1
fi
SANDBOX_RUN_SH=$0 exec "$here/.venv/bin/python" "$here/src/run.py" "$@"
