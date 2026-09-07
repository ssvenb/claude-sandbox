# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A Docker-based sandbox for running CLI coding agents autonomously. The core is repo- and
agent-agnostic: which agent runs comes from **`AGENT`** (a directory under `agents/`), and
everything opinionated (GitHub auth, cloning, branch enforcement) lives in **plugins** that can be
switched off. With the default plugins on, the host holds a GitHub App private key, the container
only ever sees short-lived installation tokens minted from it, and each run gets an isolated
feature branch (`<prefix>/<yyyymmdd>-<RUN_ID>`, e.g. `claude-code/20260902-1a2b3c`) enforced by a managed PreToolUse hook.

## Architecture

```
run.sh (host)
  ├─ sources .env and the project config, resolves AGENT and the ENABLE_<PLUGIN> flags, validates
  │  config + capabilities
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
| `claude` | Claude Code (npm) | `CLAUDE_CODE_OAUTH_TOKEN`, or the `claude-home` plugin | `claude --dangerously-skip-permissions --effort ${CLAUDE_EFFORT:-low} [prompt]` |
| `copilot` | GitHub Copilot CLI (npm) | `COPILOT_GITHUB_TOKEN`, or the `copilot-home` plugin | `copilot --allow-all [-i prompt]` |

`agents/<name>/` may contain:

| Path | Runs as | Purpose |
|------|---------|---------|
| `agent.json` | — | manifest: `name`, `description`, `managedSettings` (where plugin policy fragments are written; omit for none), optional `npmPackage` (the CLI's package, so `run.sh` can resolve its latest version into the `AGENT_VERSION` build arg), optional `git` block (`branchPrefix`, `userName`, `userEmail`) used by `git-workspace` |
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
| `git-workspace` | any | `workspace` | `git-credentials` | clone the `origin` remote of `run.sh`'s cwd into `/workspace`, per-run branch named after the agent (or `$BRANCH_PREFIX`) and the date, its git identity, resume briefing |
| `cwd-workspace` | any | `workspace` | — | bind-mounts the host's cwd (or `$HOST_WORKSPACE_DIR`) at `/workspace`; conflicts with `git-workspace`, off by default |
| `agent-workspace` | any | `workspace-mirror` | — | bind-mounts `$AGENT_WORKSPACE_DIR/<RUN_ID>` (default `~/.agent-workspace/<RUN_ID>`, created if missing) at `/workspace`, so the agent's checkout is visible on the host; complements `git-workspace`, conflicts with `cwd-workspace` |
| `branch-guard` | claude | — | `workspace` | `guard-branch.py` PreToolUse hook |
| `headroom` | claude | `llm-proxy` | — | wraps the launch command in the headroom compression proxy (`headroom-ai[proxy,mcp]`, installed in `/opt/headroom`) |
| `claude-home` | claude | `claude-home` | — | mounts the host's `~/.claude` (or `$CLAUDE_HOME_DIR`) at `/home/node/.claude` |
| `copilot-home` | copilot | `copilot-home` | — | mounts the host's `~/.copilot` (or `$COPILOT_HOME_DIR`) at `/home/node/.copilot` |
| `ca-certs` | any | `ca-certs` | — | installs the host's extra root CAs (or `$CA_CERTS_DIR`) into the container trust store, for networks behind a TLS-intercepting proxy |
| `host-network` | any | `host-network` | — | runs the container in the host's network namespace (`--network host`), so ports the agent binds are reachable from the host and the host's localhost services are reachable from the agent; conflicts with `netbird` |
| `docker-cli` | any | `docker-cli` | — | Docker CLI + compose plugin install; mounts the host's `/var/run/docker.sock` and joins `node` to a group with the socket's gid |
| `netbird` | any | `mesh-network` | — | NetBird client install; enrols the container as its own peer (`sandbox-<RUN_ID>`) with a setup key, adding `NET_ADMIN` + `/dev/net/tun`; off by default |
| `s3-auth` | any | `aws-credentials` | — | AWS CLI v2 install; mints a short-lived STS session on the host and passes only that in; off by default |
| `ssh-credentials` | any | `ssh-credentials` | — | `openssh-client` install; writes the key + `~/.ssh/config` for the agent user; off by default |
| `project-deps` | any | `project-deps` | — | installs what the target repo needs, from the project config: `apt`/`npm`/`pip` package lists (root, at boot) and `setup` commands (agent user, in `/workspace`). Nothing configured → does nothing |
| `upstream-proxy` | any | `upstream-proxy` | — | runs credential-injecting reverse proxies on the HOST, one per route from the project config, and bind-mounts their unix sockets; `socat` bridges each to a loopback port, so the agent talks plain HTTP and never sees the API keys. It also rewrites the upstream's URL out of the traffic (`rewriteUrls`, on by default): the container knows only the loopback `localUrl`, which the proxy swaps for the real endpoint on the way out and swaps back in response bodies and headers, so the upstream's hostname stays on the host too. No routes configured → does nothing |

Disable them all and the agent starts plain in an empty `/workspace` with no GitHub access.

### Writing a plugin

`plugins/<name>/` may contain:

| Path | Runs as | Purpose |
|------|---------|---------|
| `plugin.json` | — | manifest: `priority`, `defaultEnabled`, `requiredAgent`, `provides`, `requires`, `conflicts`, `requiredEnv`, `secrets` |
| `install.sh` | root, at image build | install the plugin's dependencies (e.g. `gh`); runs only when the plugin is enabled |
| `host.sh` | you, on the host | validate config; call `pass_env VAR` / `pass_value NAME VALUE` / `pass_mount HOST_PATH CONTAINER_PATH [OPTS]` / `pass_arg FLAG...` to add `docker run` args; read per-project settings with `plugin_config FILTER [DEFAULT]` / `plugin_config_json FILTER [DEFAULT]` / `project_env NAME [DEFAULT]`; set `AGENT_AUTH_PROVIDED=1` if the plugin supplies the agent's credentials itself |
| `root-init.sh` | root, in container | anything needing secrets; exports survive the `su -m node` handoff |
| `agent-init.sh` | `node`, in container | agent-visible setup; append to `$AGENT_PROMPT_FILE` to brief the agent |
| `settings.json` | — | fragment merged into the managed policy (objects merge, lists concatenate) |
| `bin/` | `node` | world-executable helpers, e.g. hook scripts (chmod 555) |
| `root/` | root | root-only helpers holding secrets (chmod 500) |

Stage scripts are *sourced*, run in `priority` order, and are all optional. Vars listed in
`secrets` are unset before the agent user takes over. Unmet `requires`/`requiredEnv`, or two
enabled plugins listing each other in `conflicts`, fail the run on the host, before the image is
built.

### Project configuration

`.env` configures the sandbox; settings that belong to the *repo being worked on* live in an
optional `.claude-sandbox.json` in `$HOST_CWD` (override: `PROJECT_CONFIG_FILE`), loaded by
`src/lib/host-project-config.sh` before plugin resolution:

```json
{ "plugins": { "upstream-proxy": { "envFile": ".env", "routes": [ ... ] } } }
```

A `host.sh` reads its own section — `.plugins["<plugin>"]`, keyed by `$PLUGIN_NAME`, no need to
name itself — with `plugin_config` (scalars) and `plugin_config_json` (objects/arrays); both take
a jq filter relative to that section plus a fallback for when the file, section or key is missing.
The file and every key in it are optional, so a plugin reading config must still work without one,
and nothing in it reaches the container except through the plugin's own `pass_*` calls. See
`.claude-sandbox.example.json`.

The worked-on repo's own `.env` is loaded centrally too, by `src/lib/host-project-env.sh`
(`$HOST_CWD/.env`, override `PROJECT_ENV_FILE`, `/dev/null` to load nothing): a `host.sh` reads one
key from it with `project_env NAME [default]` (`git-workspace` takes `BRANCH_PREFIX` this way). The
file is scanned, never sourced — it is the target repo's, so its secrets and commands stay out of
`run.sh`'s shell.

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
| `AGENT_VERSION` | core | Version of the agent's CLI baked into the image; empty (default) resolves the registry's latest on every run |
| `PROJECT_CONFIG_FILE` | core | Per-project plugin configuration (default `$HOST_CWD/.claude-sandbox.json`; optional) |
| `PROJECT_ENV_FILE` | core | The worked-on repo's `.env`, scanned for plugin settings it keeps there (default `$HOST_CWD/.env`; `/dev/null` loads nothing) |
| `CLAUDE_CODE_OAUTH_TOKEN` | agents/claude | Claude Code OAuth token for API auth (required unless a plugin sets `AGENT_AUTH_PROVIDED=1`, as `claude-home` does) |
| `CLAUDE_EFFORT` | agents/claude | Reasoning effort Claude Code runs at: `low` (default), `medium`, `high`, `xhigh`, `max` |
| `COPILOT_GITHUB_TOKEN` | agents/copilot | Fine-grained PAT with the "Copilot Requests" permission (or a Copilot/`gh` OAuth token); required unless a plugin sets `AGENT_AUTH_PROVIDED=1`, as `copilot-home` does |
| `ENABLE_GITHUB_AUTH` / `ENABLE_GIT_WORKSPACE` / `ENABLE_CWD_WORKSPACE` / `ENABLE_AGENT_WORKSPACE` / `ENABLE_BRANCH_GUARD` / `ENABLE_HEADROOM` / `ENABLE_CLAUDE_HOME` / `ENABLE_COPILOT_HOME` / `ENABLE_DOCKER_CLI` / `ENABLE_NETBIRD` / `ENABLE_S3_AUTH` / `ENABLE_SSH_CREDENTIALS` / `ENABLE_CA_CERTS` / `ENABLE_HOST_NETWORK` / `ENABLE_UPSTREAM_PROXY` / `ENABLE_PROJECT_DEPS` | core | plugin switches (default on, except `cwd-workspace`, `netbird`, `s3-auth`, `ssh-credentials`) |
| `GH_APP_ID` | github-auth | GitHub App ID |
| `GH_PRIVATE_KEY_FILE` | github-auth | Path to App's `.pem` private key |
| `GH_HOST` | github-auth | GitHub hostname for Enterprise Server (default: `github.com`) |
| `BRANCH_PREFIX` | git-workspace | Leading segment of the per-run branch name, read from the **worked-on repo's** `$HOST_CWD/.env` (not the sandbox's); `.plugins["git-workspace"].branchPrefix` in its `.claude-sandbox.json` wins over it, and with neither it defaults to the agent manifest's `branchPrefix`, else the agent's directory name. When set explicitly it also becomes the run's git identity (`user.name`, and `user.email` as `<prefix>@sandbox.local`), replacing the manifest's `userName`/`userEmail` |
| `BASE_BRANCH` | git-workspace | Branch to cut from (default: the repo's own default branch, via `origin/HEAD`) |
| `HOST_WORKSPACE_DIR` | cwd-workspace | Host dir mounted at `/workspace` (default: run.sh's cwd) |
| `AGENT_WORKSPACE_DIR` | agent-workspace | Host dir holding the per-run mirrors of `/workspace`, created if missing (default: `$HOME/.agent-workspace`; each run uses `<dir>/<RUN_ID>`) |
| `CA_CERTS_DIR` | ca-certs | Host dir holding extra root certificates, PEM or DER (default: `/usr/local/share/ca-certificates`) |
| `CLAUDE_HOME_DIR` | claude-home | Host dir mounted as the agent's `~/.claude` (default: `$HOME/.claude`) |
| `COPILOT_HOME_DIR` | copilot-home | Host dir mounted as the agent's `~/.copilot` (default: `$HOME/.copilot`) |
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
- `DISABLE_AUTOUPDATER=1` / `COPILOT_AUTO_UPDATE=false` — the agent version is pinned at image build time; `run.sh` resolves the latest release on the host and passes it as the `AGENT_VERSION` build arg, so the install layer rebuilds when (and only when) a new version is out.
- `HEADROOM_TELEMETRY=off` (set by the `headroom` plugin) — no telemetry leaves the container.
