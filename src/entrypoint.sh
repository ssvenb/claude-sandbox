#!/bin/sh
set -e

# Own the project files for the unprivileged agent user.
chown -R node:node /workspace

# shellcheck source=lib/plugins.sh
. /usr/local/lib/sandbox/plugins.sh
# shellcheck source=lib/agents.sh
. /usr/local/lib/sandbox/agents.sh

# Root stage: this is the only context that holds the secrets run.sh passed in, so anything
# needing them (minting tokens, starting refresh loops) happens here.
plugin_run_stage root-init

# Compose the enterprise policy from the fragments the enabled plugins contribute, at the path
# the selected agent reads it from (agents that have no such file declare none). Written by root
# outside /workspace and read-only, so the agent can't disable its own guardrails.
MANAGED_SETTINGS=$(agent_meta '.managedSettings // empty')
if [ -n "$MANAGED_SETTINGS" ]; then
  mkdir -p "$(dirname "$MANAGED_SETTINGS")"
  # shellcheck disable=SC2046  # word splitting is intended: one argument per fragment
  /usr/local/bin/merge-settings.py \
    /usr/local/share/sandbox/settings-base.json $(plugin_settings_files) \
    > "$MANAGED_SETTINGS"
  chmod 444 "$MANAGED_SETTINGS"
fi

# Hand off to 'node'. Drop every var the plugins declared as a secret first, so the agent only
# ever sees the short-lived derivatives the root stage exported. -m preserves that curated env.
for _secret in $(plugin_secret_vars); do
  unset "$_secret"
done
su -m -s /bin/sh node -c '/usr/local/bin/agent-setup.sh'
