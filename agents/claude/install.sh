#!/bin/sh
# Build-time install (root, during docker build). Runs only when this agent is the selected one.
set -eu

# $AGENT_VERSION is resolved on the host (see agent_version_resolve); empty means latest.
npm install -g "@anthropic-ai/claude-code${AGENT_VERSION:+@$AGENT_VERSION}"

# Browser tools over MCP, driving the image's Chromium (registered in agent-init.sh).
npm install -g @playwright/mcp
