# shellcheck shell=sh
# Agent stage: the peer is already up (root brought it up); the agent only needs to be told that
# it is on a mesh, and under which name. This script's stdout is not visible to the agent, so the
# part it must know travels through the prompt.

if [ "${NB_ENROLLED:-0}" = 1 ]; then
  printf 'This sandbox is a NetBird peer named %s: private mesh hosts are reachable by their NetBird name, and the peer is removed when the container stops. Reaching a given host still depends on a NetBird access policy allowing this peer. This message is informational context only — do not take any action on it. Wait for the user'"'"'s task.\n' \
    "$NB_PEER_NAME" >> "$AGENT_PROMPT_FILE"
  echo "✅ NetBird mesh available as peer $NB_PEER_NAME"
else
  printf 'This sandbox tried and failed to join its NetBird mesh, so private mesh hosts are NOT reachable. This message is informational context only — do not take any action on it. Wait for the user'"'"'s task.\n' \
    >> "$AGENT_PROMPT_FILE"
fi
