#!/bin/sh
# Build-time install (root, during docker build). Runs only for the selected agent.
#
# npm, not the gh.io installer: the package ships the platform executable as an optional
# dependency, so nothing is fetched from GitHub's release-asset hosts (which a TLS-intercepting
# proxy breaks), and a failure fails the build loudly rather than leaving an image with no binary.
set -eu

# $AGENT_VERSION is resolved on the host (see resolve_version in src/orchestrator/agents.py); empty means latest.
npm install -g "@github/copilot${AGENT_VERSION:+@$AGENT_VERSION}"

# The GitHub Copilot SDK, which chat.mjs drives the CLI above with for web chats. It lives outside
# any project; the copy of the runtime it bundles (some 200 MB) goes, since the one above is used.
npm install --prefix /opt/agent-sdk @github/copilot-sdk
rm -rf /opt/agent-sdk/node_modules/@github/copilot-sdk-*
