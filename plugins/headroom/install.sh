#!/bin/sh
# Build-time install (root, during docker build). Isolated venv so it can't perturb system Python,
# with only the entrypoint linked onto PATH. [proxy] pulls the server plus the JSON/AST
# compressors; no torch/ML, which is too heavy here and adds little.
set -eu

python3 -m venv /opt/headroom
/opt/headroom/bin/pip install --no-cache-dir --upgrade pip
/opt/headroom/bin/pip install --no-cache-dir "headroom-ai[proxy,mcp]"
ln -sf /opt/headroom/bin/headroom /usr/local/bin/headroom
