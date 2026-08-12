# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Docker-based sandbox for running Claude Code agents autonomously against a GitHub repo. The host machine holds a GitHub App private key; the container only ever sees short-lived installation tokens minted from it. Each run gets an isolated feature branch (`claude-code/<RUN_ID>`) enforced by a managed PreToolUse hook.

## Architecture

```
run.sh (host)
  ├─ sources .env, validates config, builds image
  └─ docker run → entrypoint.sh (root)
       ├─ mint-gh-token.py → prints installation token (RS256 JWT → GitHub API)
       ├─ background loop re-mints token every 40 min (tokens expire at 1h)
       ├─ drops GH_PRIVATE_KEY, hands off to 'node' user
       └─ agent-setup.sh (node)
            ├─ gh auth login, clone repo into /workspace
            ├─ creates or resumes claude-code/<RUN_ID> branch
            └─ headroom wrap claude --no-serena -- --dangerously-skip-permissions
```

- **guard-branch.py** — PreToolUse hook (managed-settings.json) that blocks branch switching and restricts `git push` to the agent's own branch.
- **headroom** — compression proxy (`headroom-ai[proxy,mcp]`) that sits between Claude Code and the Anthropic API, compressing context. Installed in `/opt/headroom` venv.
- **managed-settings.json** — enterprise-style policy file at `/etc/claude-code/managed-settings.json`; root-owned, read-only to agent.

## Build & Run

```bash
docker build -t claude-agent .        # build the image
./run.sh                              # fresh run (generates RUN_ID)
./run.sh --resume <6-hex-char-id>     # resume an existing run's branch
```

## Environment Variables

All env variables must have an example in `.env.example`. Configuration lives in `.env` (git-ignored).

| Variable | Purpose |
|----------|---------|
| `GH_APP_ID` | GitHub App ID |
| `GH_PRIVATE_KEY_FILE` | Path to App's `.pem` private key |
| `REPO_URL` | HTTPS clone URL of the target repo |
| `BASE_BRANCH` | Branch to cut from (default: `main`) |
| `GH_HOST` | GitHub hostname for Enterprise Server (default: `github.com`) |
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude Code OAuth token for API auth |

The volume mount in `run.sh` (`-v /home/$USER/.claude:/home/node/.claude`) ensures the container uses the host user's globally configured Claude credentials.

## Key Constraints

- The agent user (`node`) never sees the GitHub App private key — only short-lived tokens.
- Branch guard is root-owned and immutable from within the container; the agent cannot bypass it.
- `DISABLE_AUTOUPDATER=1` — Claude Code version is pinned at image build time.
- `HEADROOM_TELEMETRY=off` — no telemetry leaves the container.
