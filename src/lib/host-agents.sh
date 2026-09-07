# shellcheck shell=bash
# Host-side agent framework. Sourced by run.sh AFTER host-plugins.sh, whose helpers (die,
# pass_env, pass_mount, …) the agent host.sh scripts also use.
#
# An agent is a directory under agents/ packaging one CLI coding agent. Exactly one runs per
# container; $AGENT picks it.
#
#   agent.json     manifest read here, before anything else
#   install.sh     root, at image build — installs the CLI (only the selected agent's runs)
#   host.sh        sourced here, on the host — validates credentials, appends to DOCKER_ARGS
#   agent-init.sh  sourced by agent-setup.sh as 'node' — seeds the agent's own config
#   launch.sh      sourced by agent-setup.sh as 'node' — execs the agent with $AGENT_PROMPT

AGENT_ROOT="${AGENT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/agents}"

agent_meta() { jq -r "$1" "$AGENT_DIR/agent.json"; }

agent_resolve() {
  AGENT="${AGENT:-claude}"
  [[ "$AGENT" =~ ^[a-z0-9-]+$ ]] || die "Invalid AGENT '$AGENT' (expected lowercase letters, digits and dashes)."
  AGENT_DIR="$AGENT_ROOT/$AGENT"
  [ -f "$AGENT_DIR/agent.json" ] \
    || die "Unknown agent '$AGENT'. Available: $(cd "$AGENT_ROOT" && printf '%s ' */ | tr -d /)"
  jq -e . "$AGENT_DIR/agent.json" >/dev/null 2>&1 || die "Malformed manifest: $AGENT_DIR/agent.json"
}

# Export $AGENT_VERSION for the `docker build` arg. It is the cache key of the install layer, so
# resolving the latest release here is what makes a new upstream version rebuild that one layer
# (the in-container auto-updater is off, so without this the agent would freeze on an old release).
# Set in .env it pins explicitly; a failed registry lookup leaves it empty, which reuses the image
# as-is rather than failing the run.
agent_version_resolve() {
  local pkg
  pkg=$(agent_meta '.npmPackage // empty')
  [ -n "$pkg" ] || return 0
  if [ -n "${AGENT_VERSION:-}" ]; then
    echo "📌 $pkg@$AGENT_VERSION (pinned)"
    return 0
  fi
  AGENT_VERSION=$(npm view "$pkg" version 2>/dev/null | tr -d '[:space:]') || true
  if [ -n "$AGENT_VERSION" ]; then
    echo "📌 $pkg@$AGENT_VERSION (latest)"
  else
    echo "⚠️  Could not reach the npm registry for $pkg — keeping the version already in the image."
  fi
  export AGENT_VERSION
}

agent_host_stage() {
  if [ -f "$AGENT_DIR/host.sh" ]; then
    # shellcheck disable=SC1091  # path resolved at runtime
    . "$AGENT_DIR/host.sh"
  fi
}
