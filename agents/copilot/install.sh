#!/bin/sh
# Build-time install (root, during docker build). Runs only when this agent is the selected one.
#
# The official installer drops a standalone executable in $PREFIX/bin. The npm package
# (@github/copilot) is not used because it requires Node 22 and this image is built on Node 20.
set -eu

curl -fsSL https://gh.io/copilot-install | PREFIX=/usr/local bash
