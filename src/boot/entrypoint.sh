#!/bin/sh
set -e

# The agent's user takes the uid of the host user who started the sandbox, so what the plugins
# mount from the host is its own: claude-home's ~/.claude holds a .credentials.json only its owner
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

# Root stage: the only context holding the secrets run.sh passed in, so anything needing them
# happens here. Tokens derived from long-lived keys are minted on the host instead and arrive
# ready-made under /run/credentials (src/services/credentials/credentials.sh).
plugin_run_stage root-init

# Compose the enterprise policy from the enabled plugins' fragments, at the path the selected
# agent reads it from. Root-owned, outside /workspace and read-only, so the agent cannot disable
# its own guardrails.
MANAGED_SETTINGS=$(agent_meta '.managedSettings // empty')
if [ -n "$MANAGED_SETTINGS" ]; then
  mkdir -p "$(dirname "$MANAGED_SETTINGS")"
  # shellcheck disable=SC2046  # word splitting is intended: one argument per fragment
  /usr/local/bin/merge-settings.py \
    /usr/local/share/sandbox/settings-base.json $(plugin_settings_files) \
    > "$MANAGED_SETTINGS"
  chmod 444 "$MANAGED_SETTINGS"
fi

# Hand off to 'node', dropping every var the plugins declared as a secret first — the agent only
# ever sees the short-lived derivatives the root stage exported. setpriv leaves that curated env
# as is, and unlike `su -c` it keeps the session: su starts the command in a new one with no
# controlling terminal, so the agent's TUI never got SIGWINCH and garbled after every resize.
for _secret in $(plugin_secret_vars); do
  unset "$_secret"
done
exec setpriv --reuid=node --regid=node --init-groups /usr/local/bin/agent-setup.sh
