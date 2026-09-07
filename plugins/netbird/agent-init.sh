# shellcheck shell=sh
# Agent stage: root already brought the peer up, so all that is left is telling the agent it is on
# a mesh and under which name — stdout is invisible to it, so that has to go through the prompt.

if [ "${NB_ENROLLED:-0}" = 1 ]; then
  printf 'This sandbox is a NetBird peer named %s: private mesh hosts are reachable by their NetBird name, and the peer is removed when the container stops. Reaching a given host still depends on a NetBird access policy allowing this peer.\n' \
    "$NB_PEER_NAME" >> "$AGENT_PROMPT_FILE"
  echo "✅ NetBird mesh available as peer $NB_PEER_NAME"
else
  printf 'This sandbox tried and failed to join its NetBird mesh, so private mesh hosts are NOT reachable.\n' \
    >> "$AGENT_PROMPT_FILE"
fi
