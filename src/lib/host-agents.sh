# shellcheck shell=bash
# Host-side agent framework. Sourced by src/lib/host-stage.sh AFTER host-plugins.sh, whose helpers
# (die, pass_env, pass_mount, …) the agent host.sh scripts also use. Which agent runs, and the
# version its image installs, is src/host/agents.py's: AGENT and AGENT_DIR come from there.
#
# An agent is a directory under agents/ packaging one CLI coding agent. Exactly one runs per
# container; $AGENT picks it.
#
#   agent.json     manifest, read by src/host/agents.py before anything else
#   install.sh     root, at image build — installs the CLI (only the selected agent's runs)
#   host.sh        sourced here, on the host — validates credentials, appends to DOCKER_ARGS
#   agent-init.sh  sourced by agent-setup.sh as 'node' — seeds the agent's own config
#   launch.sh      sourced by agent-setup.sh as 'node' — execs the agent with $AGENT_PROMPT

AGENT_ROOT="${AGENT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/agents}"
AGENT="${AGENT:-claude}"
AGENT_DIR="${AGENT_DIR:-$AGENT_ROOT/$AGENT}"

agent_meta() { jq -r "$1" "$AGENT_DIR/agent.json"; }

agent_host_stage() {
  if [ -f "$AGENT_DIR/host.sh" ]; then
    # shellcheck disable=SC1091  # path resolved at runtime
    . "$AGENT_DIR/host.sh"
  fi
}
