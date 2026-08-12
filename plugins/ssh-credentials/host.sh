# shellcheck shell=bash
# Host stage: read the key on this machine and pass its contents in.
#
# Unlike github-auth's App key, this credential cannot be exchanged for a short-lived derivative —
# SSH keys have no such mechanism, so the agent user necessarily holds the key itself for as long
# as the container runs. Give the sandbox a key of its OWN (never your personal one), authorized
# only on the hosts the agent is meant to reach, and revoke it by removing it from those hosts'
# authorized_keys. Prefer a key whose reach is already narrow — e.g. one that only resolves over
# the netbird plugin's mesh.

[ -f "$SSH_PRIVATE_KEY_FILE" ] || die "SSH_PRIVATE_KEY_FILE not found: $SSH_PRIVATE_KEY_FILE"
grep -q 'PRIVATE KEY' "$SSH_PRIVATE_KEY_FILE" \
  || die "SSH_PRIVATE_KEY_FILE does not look like a private key: $SSH_PRIVATE_KEY_FILE (did you point it at the .pub?)"
if grep -q 'ENCRYPTED' "$SSH_PRIVATE_KEY_FILE"; then
  die "SSH_PRIVATE_KEY_FILE is passphrase-protected; the sandbox boots non-interactively and cannot unlock it. Use a dedicated key without a passphrase."
fi

pass_value SSH_PRIVATE_KEY "$(cat "$SSH_PRIVATE_KEY_FILE")"

# Host pattern the key is offered for, and how those names resolve. With SSH_HOST_SUFFIX set,
# `ssh myhost` becomes `ssh myhost.<suffix>` — handy for mesh/VPN domains.
pass_env SSH_HOST_PATTERN SSH_HOST_USER SSH_HOST_SUFFIX

# Pinned host keys, if you have them: with these the sandbox verifies its peers instead of
# trusting them on first use.
if [ -n "${SSH_KNOWN_HOSTS_FILE:-}" ]; then
  [ -f "$SSH_KNOWN_HOSTS_FILE" ] || die "SSH_KNOWN_HOSTS_FILE not found: $SSH_KNOWN_HOSTS_FILE"
  pass_value SSH_KNOWN_HOSTS "$(cat "$SSH_KNOWN_HOSTS_FILE")"
fi
