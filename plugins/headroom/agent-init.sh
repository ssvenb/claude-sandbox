# shellcheck shell=sh
# Runs as 'node'. Replaces the launch command so Claude Code starts behind the headroom proxy.
#
# `headroom wrap claude` boots a local proxy (127.0.0.1:8787), points ANTHROPIC_BASE_URL at it,
# and execs claude with every flag after `--` passed straight through; all of Claude's LLM calls
# then flow through headroom, which compresses context before it hits the Anthropic API and
# forwards Claude's own auth (CLAUDE_CODE_OAUTH_TOKEN) upstream unchanged. --no-serena skips the
# external Serena MCP (needs uvx/network the locked-down sandbox doesn't have); the headroom MCP
# retrieve tool stays on so compressed-away content remains reversible.
command -v headroom >/dev/null || {
  echo "❌ headroom is not installed in this image" >&2
  exit 1
}

# Telemetry off: the agent's traffic must not leave the box (data-residency).
export HEADROOM_TELEMETRY=off
export AGENT_LAUNCH_CMD="headroom wrap claude --no-serena --"
