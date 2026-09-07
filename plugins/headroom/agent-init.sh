# shellcheck shell=sh
# Runs as 'node'. Replaces the launch command so Claude Code starts behind the headroom proxy:
# `headroom wrap` boots a local proxy, points ANTHROPIC_BASE_URL at it and execs claude with
# everything after `--`, so the LLM calls are compressed on the way to the Anthropic API while
# Claude's own auth is forwarded unchanged. --no-serena skips the external Serena MCP (needs
# uvx/network this sandbox does not have); headroom's own retrieve tool stays on, so
# compressed-away content remains reversible.
command -v headroom >/dev/null || {
  echo "❌ headroom is not installed in this image" >&2
  exit 1
}

# Telemetry off: the agent's traffic must not leave the box (data residency).
export HEADROOM_TELEMETRY=off
export AGENT_LAUNCH_CMD="headroom wrap claude --no-serena --"
