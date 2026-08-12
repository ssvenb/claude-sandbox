# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Docker-based sandbox for running CLI coding agents autonomously. The core is repo- and
agent-agnostic: which agent runs comes from **`AGENT`** (a directory under `agents/`), and
everything opinionated (GitHub auth, cloning, branch enforcement) lives in **plugins** that can be
switched off. With the default plugins on, the host holds a GitHub App private key, the container
only ever sees short-lived installation tokens minted from it, and each run gets an isolated
feature branch (`claude-code/<RUN_ID>`) enforced by a managed PreToolUse hook.

## Architecture

```
run.sh (host)
  ├─ sources .env, resolves AGENT and the ENABLE_<PLUGIN> flags, validates config + capabilities
  ├─ plugin host.sh scripts, then the agent's host.sh, contribute `docker run` args (secrets stay on the host)
  └─ docker run → entrypoint.sh (root)
       ├─ plugin root-init.sh scripts (only context holding secrets)
       ├─ merges plugin settings.json fragments → the agent's `managedSettings` path
       ├─ drops declared secrets, hands off to 'node' user
       └─ agent-setup.sh (node)
            ├─ the agent's agent-init.sh (seeds its own config for a non-interactive boot)
            ├─ plugin agent-init.sh scripts (auth, /workspace provisioning, guardrails)
            └─ the agent's launch.sh → $AGENT_LAUNCH_CMD + flags + [briefing]
```

- **$AGENT_LAUNCH_CMD** — how the agent binary is started; empty means the agent's own default
  (`claude`, `copilot`), and a plugin's `agent-init.sh` may replace it with a wrapper (the
  `headroom` plugin sets `headroom wrap claude --no-serena --`).
- **settings-base.json** — the empty policy base plugin fragments are merged into by
  `src/merge-settings.py`; the result is written root-owned and read-only to the path the agent's
  manifest names (`/etc/claude-code/managed-settings.json` for `claude`).

## Agents

Exactly one agent runs per container, selected with `AGENT` (default `claude`). All agents ship in
the image, but only the selected one's `install.sh` runs at build time, and the image is tagged
`claude-agent:$AGENT`.

| Agent | CLI | Credentials | Launched as |
|-------|-----|-------------|-------------|
| `claude` | Claude Code (npm) | `CLAUDE_CODE_OAUTH_TOKEN`, or the `claude-home` plugin | `claude --dangerously-skip-permissions [prompt]` |
| `copilot` | GitHub Copilot CLI (standalone installer) | `COPILOT_GITHUB_TOKEN` | `copilot --allow-all [-i prompt]` |

`agents/<name>/` may contain:

| Path | Runs as | Purpose |
|------|---------|---------|
| `agent.json` | — | manifest: `name`, `description`, `managedSettings` (where plugin policy fragments are written; omit for none) |
| `install.sh` | root, at image build | install the CLI; runs only for the selected agent |
| `host.sh` | you, on the host | validate credentials, `pass_env` them; runs **after** every plugin's `host.sh`, so it can honour `AGENT_AUTH_PROVIDED=1` |
| `agent-init.sh` | `node` | seed the agent's own config for a non-interactive boot |
| `launch.sh` | `node` | turn `$AGENT_PROMPT` into flags and start `${AGENT_LAUNCH_CMD:-<cli>}` |

## Plugins

All plugins ship in the image; `ENABLE_<NAME>` flags in `.env` decide which run. `run.sh` passes
the resolved set to `docker build` as the `ENABLED_PLUGINS` build arg, so only enabled plugins'
`install.sh` execute and a disabled plugin's dependencies stay out of the image — changing the mix
means the next `./run.sh` rebuilds those layers. Flag names uppercase the directory name
(`github-auth` → `ENABLE_GITHUB_AUTH`); an unset flag falls back to the manifest's
`defaultEnabled`. A plugin whose `requiredAgent` is not the running agent is skipped regardless of
its flag.

| Plugin | Agent | Provides | Requires | Owns |
|--------|-------|----------|----------|------|
| `github-auth` | any | `git-credentials` | — | `gh` CLI install, App token minting + 40-min refresh loop, `gh auth login` |
| `git-workspace` | any | `workspace` | `git-credentials` | clone into `/workspace`, per-run branch, resume briefing |
| `cwd-workspace` | any | `workspace` | — | bind-mounts the host's cwd (or `$HOST_WORKSPACE_DIR`) at `/workspace`; conflicts with `git-workspace`, off by default |
| `branch-guard` | claude | — | `workspace` | `guard-branch.py` PreToolUse hook |
| `headroom` | claude | `llm-proxy` | — | wraps the launch command in the headroom compression proxy (`headroom-ai[proxy,mcp]`, installed in `/opt/headroom`) |
| `claude-home` | claude | `claude-home` | — | mounts the host's `~/.claude` (or `$CLAUDE_HOME_DIR`) at `/home/node/.claude` |
| `docker-cli` | any | `docker-cli` | — | Docker CLI + compose plugin install; mounts the host's `/var/run/docker.sock` |
| `netbird` | any | `mesh-network` | — | NetBird client install; enrols the container as its own peer (`sandbox-<RUN_ID>`) with a setup key, adding `NET_ADMIN` + `/dev/net/tun`; off by default |
| `s3-auth` | any | `aws-credentials` | — | AWS CLI v2 install; mints a short-lived STS session on the host and passes only that in; off by default |
| `ssh-credentials` | any | `ssh-credentials` | — | `openssh-client` install; writes the key + `~/.ssh/config` for the agent user; off by default |

Disable them all and the agent starts plain in an empty `/workspace` with no GitHub access.

### Writing a plugin

`plugins/<name>/` may contain:

| Path | Runs as | Purpose |
|------|---------|---------|
| `plugin.json` | — | manifest: `priority`, `defaultEnabled`, `requiredAgent`, `provides`, `requires`, `conflicts`, `requiredEnv`, `secrets` |
| `install.sh` | root, at image build | install the plugin's dependencies (e.g. `gh`); runs only when the plugin is enabled |
| `host.sh` | you, on the host | validate config; call `pass_env VAR` / `pass_value NAME VALUE` / `pass_mount HOST_PATH CONTAINER_PATH [OPTS]` / `pass_arg FLAG...` to add `docker run` args; set `AGENT_AUTH_PROVIDED=1` if the plugin supplies the agent's credentials itself |
| `root-init.sh` | root, in container | anything needing secrets; exports survive the `su -m node` handoff |
| `agent-init.sh` | `node`, in container | agent-visible setup; append to `$AGENT_PROMPT_FILE` to brief the agent |
| `settings.json` | — | fragment merged into the managed policy (objects merge, lists concatenate) |
| `bin/` | `node` | world-executable helpers, e.g. hook scripts (chmod 555) |
| `root/` | root | root-only helpers holding secrets (chmod 500) |

Stage scripts are *sourced*, run in `priority` order, and are all optional. Vars listed in
`secrets` are unset before the agent user takes over. Unmet `requires`/`requiredEnv`, or two
enabled plugins listing each other in `conflicts`, fail the run on the host, before the image is
built.

## Build & Run

```bash
./run.sh                              # fresh run (generates RUN_ID), builds claude-agent:$AGENT
./run.sh --resume <6-hex-char-id>     # resume an existing run's branch
AGENT=copilot ./run.sh                # same sandbox, GitHub Copilot CLI instead
```

## Environment Variables

All env variables must have an example in `.env.example`. Configuration lives in `.env`
(git-ignored). Only `AGENT` belongs to the core; the rest are owned by an agent or a plugin and
only required while that one is in use.

| Variable | Owner | Purpose |
|----------|-------|---------|
| `AGENT` | core | Which agent runs: a directory name under `agents/` (default `claude`) |
| `CLAUDE_CODE_OAUTH_TOKEN` | agents/claude | Claude Code OAuth token for API auth (required unless a plugin sets `AGENT_AUTH_PROVIDED=1`, as `claude-home` does) |
| `COPILOT_GITHUB_TOKEN` | agents/copilot | Fine-grained PAT with the "Copilot Requests" permission (or a Copilot/`gh` OAuth token) |
| `ENABLE_GITHUB_AUTH` / `ENABLE_GIT_WORKSPACE` / `ENABLE_CWD_WORKSPACE` / `ENABLE_BRANCH_GUARD` / `ENABLE_HEADROOM` / `ENABLE_CLAUDE_HOME` / `ENABLE_DOCKER_CLI` / `ENABLE_NETBIRD` / `ENABLE_S3_AUTH` / `ENABLE_SSH_CREDENTIALS` | core | plugin switches (default on, except `cwd-workspace`, `netbird`, `s3-auth`, `ssh-credentials`) |
| `GH_APP_ID` | github-auth | GitHub App ID |
| `GH_PRIVATE_KEY_FILE` | github-auth | Path to App's `.pem` private key |
| `GH_HOST` | github-auth | GitHub hostname for Enterprise Server (default: `github.com`) |
| `REPO_URL` | git-workspace | HTTPS clone URL of the target repo |
| `BASE_BRANCH` | git-workspace | Branch to cut from (default: `main`) |
| `HOST_WORKSPACE_DIR` | cwd-workspace | Host dir mounted at `/workspace` (default: run.sh's cwd) |
| `CLAUDE_HOME_DIR` | claude-home | Host dir mounted as the agent's `~/.claude` (default: `$HOME/.claude`) |
| `NB_SETUP_KEY` | netbird | NetBird setup key the peer enrols with (the PAT never enters the container) |
| `NB_MANAGEMENT_URL` | netbird | Self-hosted management server (default: NetBird Cloud) |
| `NB_HOSTNAME` | netbird | Peer name in the dashboard (default: `sandbox-<RUN_ID>`) |
| `S3_ROLE_ARN` | s3-auth | Role assumed on the host for the sandbox session; unset falls back to the host profile's current credentials |
| `S3_SESSION_DURATION` | s3-auth | Assumed-role session lifetime in seconds (default: 3600) |
| `AWS_REGION` / `AWS_PROFILE` | s3-auth | Region handed to the container; host profile used for minting |
| `S3_ENDPOINT_URL` / `S3_BUCKET` | s3-auth | Endpoint for S3-compatible providers; bucket named in the agent's briefing |
| `SSH_PRIVATE_KEY_FILE` | ssh-credentials | Host path to the (passphrase-less) key installed for the agent |
| `SSH_HOST_PATTERN` / `SSH_HOST_USER` / `SSH_HOST_SUFFIX` | ssh-credentials | `~/.ssh/config` stanza: hosts the key is offered for, login user, domain appended to bare names |
| `SSH_KNOWN_HOSTS_FILE` | ssh-credentials | Host path to a known_hosts file to pin peers (default: `StrictHostKeyChecking=accept-new`) |

Volume mounts are contributed by plugins via `pass_mount`; the core `docker run` command has none.

## Key Constraints

- The agent user (`node`) never sees the GitHub App private key — only short-lived tokens.
- `/opt/plugins` and `/opt/agents` are root-owned and immutable from within the container, so the agent cannot edit or disable its own guardrails.
- `DISABLE_AUTOUPDATER=1` / `COPILOT_AUTO_UPDATE=false` — the agent version is pinned at image build time.
- `HEADROOM_TELEMETRY=off` (set by the `headroom` plugin) — no telemetry leaves the container.
