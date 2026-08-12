#!/bin/sh
# Build-time install (root, during docker build). Runs only when this agent is the selected one.
set -eu

npm install -g @anthropic-ai/claude-code
