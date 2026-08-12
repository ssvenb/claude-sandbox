# shellcheck shell=bash
# Host-side agent framework. Sourced by run.sh (bash, on YOUR machine) AFTER host-plugins.sh,
# whose helpers (die, pass_env, pass_mount, …) the agent host.sh scripts also use.
#
# An agent is a directory under agents/ that packages one CLI coding agent: how it is installed
# into the image, how it authenticates, and how it is finally launched. Exactly one agent runs
# per container; $AGENT picks it.
#
#   agent.json     manifest read here, before anything else
#   install.sh     root, at image build — installs the CLI (only the selected agent's runs)
#   host.sh        sourced here, on the host — validates credentials, appends to DOCKER_ARGS
#   agent-init.sh  sourced by agent-setup.sh as 'node' — seeds the agent's own config
#   launch.sh      sourced by agent-setup.sh as 'node' — execs the agent with $AGENT_PROMPT

AGENT_ROOT="${AGENT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/agents}"

agent_meta() { jq -r "$1" "$AGENT_DIR/agent.json"; }

# Pick the agent named by $AGENT (default: claude) and fail fast if it does not exist.
agent_resolve() {
  AGENT="${AGENT:-claude}"
  [[ "$AGENT" =~ ^[a-z0-9-]+$ ]] || die "Invalid AGENT '$AGENT' (expected lowercase letters, digits and dashes)."
  AGENT_DIR="$AGENT_ROOT/$AGENT"
  [ -f "$AGENT_DIR/agent.json" ] \
    || die "Unknown agent '$AGENT'. Available: $(cd "$AGENT_ROOT" && printf '%s ' */ | tr -d /)"
  jq -e . "$AGENT_DIR/agent.json" >/dev/null 2>&1 || die "Malformed manifest: $AGENT_DIR/agent.json"
}

# Source the agent's host.sh so it can validate its credentials and contribute docker run args.
agent_host_stage() {
  if [ -f "$AGENT_DIR/host.sh" ]; then
    # shellcheck disable=SC1091  # path resolved at runtime
    . "$AGENT_DIR/host.sh"
  fi
}
