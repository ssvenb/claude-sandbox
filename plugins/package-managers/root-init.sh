# shellcheck shell=sh
# Root stage: let the agent user run apt-get/apt as root, nothing else. This is NOT a security
# boundary: apt runs maintainer scripts and accepts -o options, so whoever can call it as root can
# become root, and root can rewrite the managed policy and read what the root stage holds. That is
# the trade-off of leaving it on: disable it (ENABLE_PACKAGE_MANAGERS=0) where that matters.

cat > /etc/sudoers.d/package-managers <<'SUDOERS'
Defaults:node !requiretty
node ALL=(root) NOPASSWD: /usr/bin/apt-get, /usr/bin/apt
SUDOERS
chmod 440 /etc/sudoers.d/package-managers
