#!/bin/sh
# Build-time install (root, during docker build). Runs only when this agent is the selected one.
set -eu

# $AGENT_VERSION is resolved on the host (see resolve_version in src/host/agents.py); empty means latest.
npm install -g "@anthropic-ai/claude-code${AGENT_VERSION:+@$AGENT_VERSION}"

# Browser tools over MCP, driving the image's Chromium (registered in agent-init.sh).
npm install -g @playwright/mcp

# The Claude Agent SDK, which chat.mjs drives the CLI above with for web chats. It lives outside
# any project; the copy of the CLI it bundles (some 350 MB) goes, since the one above is used.
npm install --prefix /opt/agent-sdk @anthropic-ai/claude-agent-sdk
rm -rf /opt/agent-sdk/node_modules/@anthropic-ai/claude-agent-sdk-*
