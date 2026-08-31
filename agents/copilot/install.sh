#!/bin/sh
# Build-time install (root, during docker build). Runs only when this agent is the selected one.
#
# The npm package ships the platform executable as an optional dependency
# (@github/copilot-linux-x64 & co), so nothing is fetched from GitHub's release-asset hosts —
# which the standalone gh.io installer does, and which a TLS-intercepting proxy breaks. npm also
# fails the build loudly, unlike the installer's `curl | bash` (curl's exit status is swallowed
# by the pipe, leaving an image with no copilot binary).
set -eu

npm install -g @github/copilot
