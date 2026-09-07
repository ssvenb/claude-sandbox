# shellcheck shell=sh
# Container-side agent framework. Sourced by entrypoint.sh (root) and agent-setup.sh (node).
# $AGENT was already resolved and validated on the host; here we only locate it and run its stages.

AGENT_ROOT="${AGENT_ROOT:-/opt/agents}"
AGENT="${AGENT:-claude}"
AGENT_DIR="$AGENT_ROOT/$AGENT"
export AGENT AGENT_DIR

[ -f "$AGENT_DIR/agent.json" ] || {
  echo "❌ Unknown agent '$AGENT' — no manifest at $AGENT_DIR/agent.json" >&2
  exit 1
}

agent_meta() { jq -r "$1" "$AGENT_DIR/agent.json"; }

# Run one lifecycle stage ("agent-init" / "launch"). SOURCED, so exports reach the rest of boot.
agent_run_stage() {
  if [ -f "$AGENT_DIR/$1.sh" ]; then
    # shellcheck disable=SC1090  # path resolved at runtime
    . "$AGENT_DIR/$1.sh"
  fi
  return 0
}
