# shellcheck shell=sh
# Agent stage (runs as 'node'). Seeds Claude Code's config so it boots non-interactively: skip
# onboarding, accept the --dangerously-skip-permissions warning, and trust /workspace.

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
    | .projects["/workspace"].hasTrustDialogAccepted = true' \
   "$CONFIG" > "$tmp" && mv -f "$tmp" "$CONFIG"
unset CONFIG tmp
