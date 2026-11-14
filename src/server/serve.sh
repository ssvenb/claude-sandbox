#!/bin/sh
# The web UI's server (src/server/server.py), in this checkout's uv environment. Arguments are its own:
#   serve.sh [--port 8787] [--bind 127.0.0.1] [--allow-host NAME]... [--projects FILE]
here=$(dirname "$(readlink -f "$0")")/../..
if [ ! -x "$here/.venv/bin/python" ]; then
  command -v uv >/dev/null || { echo "❌ uv is required (https://docs.astral.sh/uv/): run $here/install.sh" >&2; exit 1; }
  uv sync --project "$here" --frozen --no-dev >&2 || exit 1
fi
exec "$here/.venv/bin/python" "$here/src/server/server.py" "$@"
