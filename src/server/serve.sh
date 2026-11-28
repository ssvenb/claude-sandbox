#!/bin/sh
# The web UI's server (src/server/server.py), in this checkout's uv environment. Arguments are its own:
#   serve.sh [--port 8787] [--bind 127.0.0.1] [--allow-host NAME]... [--projects FILE]
here=$(dirname "$(readlink -f "$0")")/../..
# Synced on every start (a no-op when it already is): a checkout pulled by hand may need what a
# newer server imports.
if command -v uv >/dev/null; then
  uv sync --project "$here" --frozen --no-dev --inexact >&2 || exit 1
elif [ ! -x "$here/.venv/bin/python" ]; then
  echo "❌ uv is required (https://docs.astral.sh/uv/): run $here/install.sh" >&2
  exit 1
fi
exec "$here/.venv/bin/python" "$here/src/server/server.py" "$@"
