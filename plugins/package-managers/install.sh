#!/bin/sh
# Build-time install (root, during docker build). No sudo: the agent installs system packages with
# apt-home, which unpacks them into its own home and never runs anything as root.
set -eu

ln -sf /opt/plugins/package-managers/bin/apt-home /usr/local/bin/apt-home
