# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Docker-based sandbox for running Claude Code agents autonomously. The core is repo-agnostic: everything opinionated (GitHub auth, cloning, branch enforcement) lives in **plugins** that can be switched off. With the default plugins on, the host holds a GitHub App private key, the container only ever sees short-lived installation tokens minted from it, and each run gets an isolated feature branch (`claude-code/<RUN_ID>`) enforced by a managed PreToolUse hook.

## Architecture

```
run.sh (host)
  ├─ sources .env, resolves ENABLE_<PLUGIN> flags, validates config + capabilities
  ├─ plugin host.sh scripts contribute `docker run` args (secrets stay on the host)
  └─ docker run → entrypoint.sh (root)
       ├─ plugin root-init.sh scripts (only context holding secrets)
       ├─ merges plugin settings.json fragments → /etc/claude-code/managed-settings.json
       ├─ drops declared secrets, hands off to 'node' user
       └─ agent-setup.sh (node)
            ├─ plugin agent-init.sh scripts (auth, /workspace provisioning, guardrails)
            ├─ seeds ~/.claude.json for non-interactive boot
            └─ $AGENT_LAUNCH_CMD --dangerously-skip-permissions [briefing]
```

- **$AGENT_LAUNCH_CMD** — how Claude is started; defaults to `claude`, and a plugin's `agent-init.sh` may replace it with a wrapper (the `headroom` plugin sets `headroom wrap claude --no-serena --`).
- **settings-base.json** — the empty policy base plugin fragments are merged into by `src/merge-settings.py`; the result is written root-owned and read-only to `/etc/claude-code/managed-settings.json`.

## Plugins

All plugins ship in the image; `ENABLE_<NAME>` flags in `.env` decide at container start which run, so changing the mix needs no rebuild. Flag names uppercase the directory name (`github-auth` → `ENABLE_GITHUB_AUTH`); an unset flag falls back to the manifest's `defaultEnabled`.

| Plugin | Provides | Requires | Owns |
|--------|----------|----------|------|
| `github-auth` | `git-credentials` | — | App token minting + 40-min refresh loop, `gh auth login` |
| `git-workspace` | `workspace` | `git-credentials` | clone into `/workspace`, per-run branch, resume briefing |
| `branch-guard` | — | `workspace` | `guard-branch.py` PreToolUse hook |
| `headroom` | `llm-proxy` | — | wraps the launch command in the headroom compression proxy (`headroom-ai[proxy,mcp]`, installed in `/opt/headroom`) |

Disable them all and the agent starts plain `claude` in an empty `/workspace` with no GitHub access.

### Writing a plugin

`plugins/<name>/` may contain:

| Path | Runs as | Purpose |
|------|---------|---------|
| `plugin.json` | — | manifest: `priority`, `defaultEnabled`, `provides`, `requires`, `requiredEnv`, `secrets` |
| `host.sh` | you, on the host | validate config; call `pass_env VAR` / `pass_value NAME VALUE` to add `docker run` args |
| `root-init.sh` | root, in container | anything needing secrets; exports survive the `su -m node` handoff |
| `agent-init.sh` | `node`, in container | agent-visible setup; append to `$AGENT_PROMPT_FILE` to brief the agent |
| `settings.json` | — | fragment merged into the managed policy (objects merge, lists concatenate) |
| `bin/` | `node` | world-executable helpers, e.g. hook scripts (chmod 555) |
| `root/` | root | root-only helpers holding secrets (chmod 500) |

Stage scripts are *sourced*, run in `priority` order, and are all optional. Vars listed in `secrets` are unset before the agent user takes over. Unmet `requires`/`requiredEnv` fail the run on the host, before the image is built.

## Build & Run

```bash
docker build -t claude-agent .        # build the image
./run.sh                              # fresh run (generates RUN_ID)
./run.sh --resume <6-hex-char-id>     # resume an existing run's branch
```

## Environment Variables

All env variables must have an example in `.env.example`. Configuration lives in `.env` (git-ignored). Only `CLAUDE_CODE_OAUTH_TOKEN` belongs to the core; the rest are owned by a plugin and only required while it is enabled.

| Variable | Owner | Purpose |
|----------|-------|---------|
| `CLAUDE_CODE_OAUTH_TOKEN` | core | Claude Code OAuth token for API auth |
| `ENABLE_GITHUB_AUTH` / `ENABLE_GIT_WORKSPACE` / `ENABLE_BRANCH_GUARD` / `ENABLE_HEADROOM` | core | plugin switches (default on) |
| `GH_APP_ID` | github-auth | GitHub App ID |
| `GH_PRIVATE_KEY_FILE` | github-auth | Path to App's `.pem` private key |
| `GH_HOST` | github-auth | GitHub hostname for Enterprise Server (default: `github.com`) |
| `REPO_URL` | git-workspace | HTTPS clone URL of the target repo |
| `BASE_BRANCH` | git-workspace | Branch to cut from (default: `main`) |

The volume mount in `run.sh` (`-v /home/$USER/.claude:/home/node/.claude`) ensures the container uses the host user's globally configured Claude credentials.

## Key Constraints

- The agent user (`node`) never sees the GitHub App private key — only short-lived tokens.
- `/opt/plugins` is root-owned and immutable from within the container, so the agent cannot edit or disable its own guardrails.
- `DISABLE_AUTOUPDATER=1` — Claude Code version is pinned at image build time.
- `HEADROOM_TELEMETRY=off` (set by the `headroom` plugin) — no telemetry leaves the container.
