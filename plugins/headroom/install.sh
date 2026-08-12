#!/bin/sh
# Build-time install (root, during docker build). Headroom compression proxy, used by this
# plugin's agent-init.sh to wrap the Claude launch command. Installed into an isolated venv so
# it can't perturb system Python; [proxy] pulls the FastAPI/uvicorn server + core compressors
# (no torch/ML — too heavy for the sandbox, and the JSON/AST compressors deliver most of the
# savings). Only the entrypoint is linked onto PATH, keeping the venv's python out of it.
set -eu

python3 -m venv /opt/headroom
/opt/headroom/bin/pip install --no-cache-dir --upgrade pip
/opt/headroom/bin/pip install --no-cache-dir "headroom-ai[proxy,mcp]"
ln -sf /opt/headroom/bin/headroom /usr/local/bin/headroom
