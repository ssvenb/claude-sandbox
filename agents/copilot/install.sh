#!/bin/sh
# Build-time install (root, during docker build). Runs only for the selected agent.
#
# npm, not the gh.io installer: the package ships the platform executable as an optional
# dependency, so nothing is fetched from GitHub's release-asset hosts (which a TLS-intercepting
# proxy breaks), and a failure fails the build loudly rather than leaving an image with no binary.
set -eu

# $AGENT_VERSION is resolved on the host (see agent_version_resolve); empty means latest.
npm install -g "@github/copilot${AGENT_VERSION:+@$AGENT_VERSION}"
