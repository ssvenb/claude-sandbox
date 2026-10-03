# shellcheck shell=sh
# Agent stage (runs as 'node'). Seeds Claude Code's config so it boots non-interactively: skip
# onboarding, accept the --dangerously-skip-permissions warning, and trust /workspace. Also registers
# the Playwright MCP server on the image's headless Chromium, so the agent has browser tools.

# The global npm prefix is root-owned, so the auto-updater could not write there anyway; the
# version is pinned at image build time.
export DISABLE_AUTOUPDATER=1

CONFIG="$HOME/.claude.json"
[ -f "$CONFIG" ] || echo '{}' > "$CONFIG"
tmp=$(mktemp)
jq '.hasCompletedOnboarding = true
    | .theme = (.theme // "dark")
    | .bypassPermissionsModeAccepted = true
    | .skipDangerousModePermissionPrompt = true
    | .projects["/workspace"].hasTrustDialogAccepted = true
    | .mcpServers.playwright = {type: "stdio", command: "playwright-mcp",
        args: ["--headless", "--isolated", "--no-sandbox", "--executable-path", "/usr/bin/chromium"]}' \
   "$CONFIG" > "$tmp" && mv -f "$tmp" "$CONFIG"
unset CONFIG tmp
