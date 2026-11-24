#!/bin/sh
set -e

# The agent's user takes the uid of the host user who started the sandbox, so what the plugins
# mount from the host is its own: Claude's ~/.claude (CLAUDE_HOME_MOUNT) holds a .credentials.json only its owner
# may read, and a web server running as a service user (not uid 1000) signs that one in. -xdev: the
# image's files only, never the mounts. Root (rootless docker maps it to the host user) keeps node.
old=$(id -u node)
if [ -n "${HOST_UID:-}" ] && [ "$HOST_UID" != 0 ] && [ "$HOST_UID" != "$old" ]; then
  sed -i "s/^node:\([^:]*\):$old:/node:\1:$HOST_UID:/" /etc/passwd  # not usermod: it re-owns the mounts too
  find /home/node /ms-playwright -xdev -user "$old" -exec chown -h node {} +
fi
unset old

# Own the project files for the unprivileged agent user. Skip character devices: those are the
# read-only /dev/null masks cwd-workspace lays over secret files, and chowning them fails.
skip=""
for p in ${CWD_WORKSPACE_HIDDEN:-}; do skip="$skip ! -path $p"; done
# shellcheck disable=SC2086  # $skip is a deliberately word-split argument list
find /workspace -xdev ! -type c $skip -exec chown node:node {} +
unset skip p

# shellcheck source=lib/plugins.sh
. /usr/local/lib/sandbox/plugins.sh
# shellcheck source=lib/agents.sh
. /usr/local/lib/sandbox/agents.sh

# Root stage: the setup that needs root (a trust store, a daemon, packages, a device's group).
# Not a boundary: everything in the container is the agent's, root included (it has the docker
# group). Tokens derived from long-lived keys are minted on the host and arrive ready-made under
# /run/credentials (src/services/credentials/credentials.sh).
plugin_run_stage root-init

# Compose the enterprise policy from the enabled plugins' fragments, at the path the selected
# agent reads it from. Root-owned, outside /workspace and read-only: a guardrail the agent does not
# edit by accident, not one it could not get around.
MANAGED_SETTINGS=$(agent_meta '.managedSettings // empty')
if [ -n "$MANAGED_SETTINGS" ]; then
  mkdir -p "$(dirname "$MANAGED_SETTINGS")"
  # shellcheck disable=SC2046  # word splitting is intended: one argument per fragment
  /usr/local/bin/merge-settings.py \
    /usr/local/share/sandbox/settings-base.json $(plugin_settings_files) \
    > "$MANAGED_SETTINGS"
  chmod 444 "$MANAGED_SETTINGS"
fi

# Hand off to 'node', which the agent's CLI wants to run as (and which owns what is mounted from the
# host). setpriv leaves the env as is, and unlike `su -c` it keeps the session: su starts the
# command in a new one with no controlling terminal, so the agent's TUI never got SIGWINCH and
# garbled after every resize.
exec setpriv --reuid=node --regid=node --init-groups /usr/local/bin/agent-setup.sh
