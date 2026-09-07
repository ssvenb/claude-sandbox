# shellcheck shell=sh
# Agent stage: write the key and client config into the agent user's ~/.ssh — as node, because node
# is the user that runs ssh and OpenSSH refuses a key file other users can read.

mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"

# %s, not %b, so the key body isn't mangled by escape interpretation; the trailing newline is added
# back because the host's command substitution stripped it and OpenSSH rejects a key without one.
printf '%s\n' "$SSH_PRIVATE_KEY" > "$HOME/.ssh/sandbox_key"
chmod 600 "$HOME/.ssh/sandbox_key"

# Pinned host keys let us verify strictly; without them, trust-on-first-use is the only option that
# still boots unattended.
if [ -n "${SSH_KNOWN_HOSTS:-}" ]; then
  printf '%s\n' "$SSH_KNOWN_HOSTS" > "$HOME/.ssh/known_hosts"
  chmod 600 "$HOME/.ssh/known_hosts"
  _ssh_strict=yes
else
  _ssh_strict=accept-new
fi

# IdentitiesOnly stops ssh offering these hosts any other key it happens to find (e.g. in a mounted
# home directory).
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

printf 'An SSH key for %s is installed at ~/.ssh/sandbox_key and wired up in ~/.ssh/config%s.\n' \
  "${SSH_HOST_PATTERN:-any host}" \
  "${SSH_HOST_USER:+, logging in as $SSH_HOST_USER}" \
  >> "$AGENT_PROMPT_FILE"

echo "✅ SSH key installed for ${SSH_HOST_PATTERN:-*}"
