# shellcheck shell=sh
# Agent stage: write the key and client config into the agent user's ~/.ssh. This runs as node
# because node is the user that will actually run ssh — the key is useless to the agent anywhere
# else, and OpenSSH refuses a key file that other users can read.

mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"

# %s (not %b) so the base64 body isn't mangled by escape interpretation; the trailing newline is
# added back because the host's command substitution stripped it and OpenSSH rejects a key
# without one.
printf '%s\n' "$SSH_PRIVATE_KEY" > "$HOME/.ssh/sandbox_key"
chmod 600 "$HOME/.ssh/sandbox_key"

# With pinned host keys we can verify strictly; without them, trust-on-first-use is the only
# option that still boots unattended.
if [ -n "${SSH_KNOWN_HOSTS:-}" ]; then
  printf '%s\n' "$SSH_KNOWN_HOSTS" > "$HOME/.ssh/known_hosts"
  chmod 600 "$HOME/.ssh/known_hosts"
  _ssh_strict=yes
else
  _ssh_strict=accept-new
fi

# IdentitiesOnly keeps ssh from offering any other key it happens to find (e.g. inside a mounted
# home directory) to these hosts.
{
  echo "Host ${SSH_HOST_PATTERN:-*}"
  [ -n "${SSH_HOST_SUFFIX:-}" ] && echo "    HostName %h.${SSH_HOST_SUFFIX}"
  [ -n "${SSH_HOST_USER:-}" ] && echo "    User ${SSH_HOST_USER}"
  echo "    IdentityFile ~/.ssh/sandbox_key"
  echo "    IdentitiesOnly yes"
  echo "    StrictHostKeyChecking $_ssh_strict"
} > "$HOME/.ssh/config"
chmod 600 "$HOME/.ssh/config"
unset _ssh_strict

printf 'An SSH key for %s is installed at ~/.ssh/sandbox_key and wired up in ~/.ssh/config%s. This message is informational context only — do not take any action on it. Wait for the user'"'"'s task.\n' \
  "${SSH_HOST_PATTERN:-any host}" \
  "${SSH_HOST_USER:+, logging in as $SSH_HOST_USER}" \
  >> "$AGENT_PROMPT_FILE"

echo "✅ SSH key installed for ${SSH_HOST_PATTERN:-*}"
