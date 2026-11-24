# shellcheck shell=bash
# Host-side agent framework. Sourced by src/contract/host/stage.sh AFTER plugins.sh, whose helpers
# (die, pass_env, pass_mount, …) the agent host.sh scripts also use. Which agent runs, and the
# version its image installs, is src/orchestrator/agents.py's: AGENT and AGENT_DIR come from there.
#
# An agent is a directory under agents/ packaging one CLI coding agent. Exactly one runs per
# container; $AGENT picks it.
#
#   agent.json     manifest, read by src/orchestrator/agents.py before anything else
#   install.sh     root, at image build — installs the CLI (only the selected agent's runs)
#   home.sh        sourced here, on the host, BEFORE the plugins' host stages — mounts the agent's
#                  home; a container beside the sandbox may take its args too (AGENT_HOME_ARGS)
#   host.sh        sourced here, on the host — validates credentials, appends to DOCKER_ARGS
#   agent-init.sh  sourced by agent-setup.sh as 'node' — seeds the agent's own config
#   launch.sh      sourced by agent-setup.sh as 'node' — execs the agent with $AGENT_PROMPT
#   after-sign-in.sh  run by sh on the host by the web server (src/server/server.py) once its
#                  `signIn` succeeded — e.g. hands the new login to the runs still going

AGENT_ROOT="${AGENT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)/agents}"
AGENT="${AGENT:-claude}"
AGENT_DIR="${AGENT_DIR:-$AGENT_ROOT/$AGENT}"

agent_meta() { jq -r "$1" "$AGENT_DIR/agent.json"; }

# The agent's home (its config, its login): what home.sh adds to DOCKER_ARGS is kept in
# AGENT_HOME_ARGS too, for a sibling container of the run's (dev-server's demo) to take.
AGENT_HOME_ARGS=()
agent_home_stage() {
  local from=${#DOCKER_ARGS[@]}
  if [ -f "$AGENT_DIR/home.sh" ]; then
    # shellcheck disable=SC1091  # path resolved at runtime
    . "$AGENT_DIR/home.sh"
  fi
  AGENT_HOME_ARGS=(${DOCKER_ARGS[@]+"${DOCKER_ARGS[@]:$from}"})
}

agent_host_stage() {
  if [ -f "$AGENT_DIR/host.sh" ]; then
    # shellcheck disable=SC1091  # path resolved at runtime
    . "$AGENT_DIR/host.sh"
  fi
}
