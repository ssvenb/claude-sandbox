# claude-sandbox

A Docker sandbox for running CLI coding agents autonomously.

The core is repo- and agent-agnostic: it builds an image, starts a container, and launches the
selected agent with every permission prompt disabled. Which agent that is comes from **`AGENT`**
(see [agents/](agents)); everything opinionated — GitHub authentication, cloning a repo, pinning
the agent to a branch, mounting your `~/.claude` — lives in **plugins** that can be switched off
individually. With the defaults, the GitHub App private key never leaves your machine (the
container only sees short-lived installation tokens), and each run works on its own
`claude-code/<RUN_ID>` branch enforced by a managed hook the agent cannot edit.

## Quick start

```bash
cp .env.example .env      # pick AGENT, fill in its token and any plugin variables
./run.sh                  # build + fresh run (generates a RUN_ID)
./run.sh --resume a1b2c3  # re-attach to an existing run's branch
```

`jq` is required on the host. `run.sh` builds the image itself (tagged `claude-agent:$AGENT`), so
a manual `docker build -t claude-agent:claude --build-arg AGENT=claude .` is only needed if you
want to build without running.

## How a run boots

```
run.sh (host)
  ├─ sources .env, resolves AGENT and the ENABLE_<PLUGIN> flags, validates config + capabilities
  ├─ each enabled plugin's host.sh, then the agent's host.sh, contribute `docker run` args
  ├─ docker build --build-arg AGENT=... --build-arg ENABLED_PLUGINS=...
  └─ docker run → entrypoint.sh (root)
       ├─ chown /workspace to node
       ├─ each enabled plugin's root-init.sh (only context that holds secrets)
       ├─ merges settings-base.json + plugin settings.json → the agent's managedSettings path (0444)
       ├─ unsets every var declared in a plugin's `secrets`, then `su -m node`
       └─ agent-setup.sh (node)
            ├─ the agent's agent-init.sh (seeds its own config for a non-interactive boot)
            ├─ each enabled plugin's agent-init.sh (auth, /workspace, guardrails, briefing)
            └─ the agent's launch.sh → $AGENT_LAUNCH_CMD + flags + [briefing]
```

Two variables steer the tail of that sequence:

- **`$AGENT_LAUNCH_CMD`** — how the agent binary is started; empty means the agent's own default
  (`claude`, `copilot`). An `agent-init.sh` may replace it with a wrapper (the `headroom` plugin
  sets `headroom wrap claude --no-serena --`).
- **`$AGENT_PROMPT_FILE`** — a temp file plugins append to during the agent stage. Its contents
  become the agent's initial prompt. Stage script stdout is *not* visible to the agent, so
  anything the agent must know has to go through this file.

## Agents

Exactly one agent runs per container, chosen with `AGENT` (default `claude`). Every agent's files
ship in the image, but only the selected one's `install.sh` runs, so an unused agent's binaries
stay out of it; the image is tagged per agent, so switching back and forth doesn't rebuild.

| Agent | CLI | Credentials | Launched as |
|-------|-----|-------------|-------------|
| `claude` | Claude Code (`@anthropic-ai/claude-code`, npm) | `CLAUDE_CODE_OAUTH_TOKEN`, or the `claude-home` plugin | `claude --dangerously-skip-permissions [prompt]` |
| `copilot` | GitHub Copilot CLI (standalone build from `gh.io/copilot-install`) | `COPILOT_GITHUB_TOKEN` | `copilot --allow-all [-i prompt]` |

### Anatomy of an agent

An agent is a directory under `agents/<name>/`. Only `agent.json` is required; the scripts are
**sourced**, exactly like plugin stage scripts.

| Path | Runs as | When |
|------|---------|------|
| `agent.json` | — | read on the host, before anything else |
| `install.sh` | root | image build, only for the selected agent |
| `host.sh` | you | on the host, **after** every plugin's `host.sh` |
| `agent-init.sh` | `node` | in the container, before the plugins' agent stage |
| `launch.sh` | `node` | last: turns `$AGENT_PROMPT` into flags and starts the agent |

`agent.json` carries `name`, `description`, and `managedSettings` — the path the agent reads its
managed (enterprise) policy from, which is where plugin `settings.json` fragments are merged.
Omit it and no policy file is written.

Because `host.sh` runs after the plugin host stage, it can see `AGENT_AUTH_PROVIDED=1` from a
plugin that supplies credentials itself and skip its own token check:

```sh
# shellcheck shell=bash
[ "${AGENT_AUTH_PROVIDED:-0}" = 1 ] || : "${CLAUDE_CODE_OAUTH_TOKEN:?must be set in .env}"
pass_env CLAUDE_CODE_OAUTH_TOKEN
```

## Plugins

All plugins ship in the image; `ENABLE_<NAME>` flags in `.env` decide which ones run. The flag
name uppercases the directory name and turns `-` into `_` (`github-auth` → `ENABLE_GITHUB_AUTH`);
an unset flag falls back to the manifest's `defaultEnabled`. Accepted values are
`1|true|yes|on` / `0|false|no|off`; anything else aborts the run. A plugin whose `requiredAgent`
is not the running agent is skipped, however its flag is set.

`run.sh` passes the resolved set to `docker build` as the `ENABLED_PLUGINS` build arg, so only
enabled plugins' `install.sh` execute and a disabled plugin's dependencies stay out of the image
— changing the mix means the next `./run.sh` rebuilds those layers.

| Plugin | Priority | Default | Agent | Provides | Requires | Owns |
|--------|---------:|---------|-------|----------|----------|------|
| `claude-home` | 5 | on | claude | `claude-home` | — | mounts the host's `~/.claude` (or `$CLAUDE_HOME_DIR`) at `/home/node/.claude`; sets `AGENT_AUTH_PROVIDED=1` |
| `docker-cli` | 5 | on | any | `docker-cli` | — | Docker CLI + compose plugin install; mounts the host's `/var/run/docker.sock` |
| `netbird` | 5 | off | any | `mesh-network` | — | NetBird client install; enrols the container as its own peer (`sandbox-<RUN_ID>`) from `$NB_SETUP_KEY`, adding `NET_ADMIN` + `/dev/net/tun` |
| `github-auth` | 10 | on | any | `git-credentials` | — | `gh` CLI install, App token minting + 40-min refresh loop, `gh auth login` |
| `s3-auth` | 10 | off | any | `aws-credentials` | — | AWS CLI v2 install; mints a short-lived STS session on the host, passes only that in |
| `ssh-credentials` | 15 | off | any | `ssh-credentials` | — | `openssh-client` install; writes `~/.ssh/sandbox_key` + `~/.ssh/config` for the agent user |
| `git-workspace` | 20 | on | any | `workspace` | `git-credentials` | clone into `/workspace`, per-run branch, resume briefing |
| `cwd-workspace` | 20 | off | any | `workspace` | — | bind-mounts the host's cwd (or `$HOST_WORKSPACE_DIR`) at `/workspace`; conflicts with `git-workspace` |
| `branch-guard` | 30 | on | claude | — | `workspace` | `guard-branch.py` PreToolUse hook |
| `headroom` | 40 | on | claude | `llm-proxy` | — | wraps the launch command in the headroom compression proxy (`headroom-ai[proxy,mcp]` in `/opt/headroom`) |

Disable them all and the agent starts plain, in an empty `/workspace` with no GitHub access.

## Anatomy of a plugin

A plugin is a directory under `plugins/<name>/`. Every file is optional except `plugin.json`.
Each script belongs to exactly one privilege stage, and all of them are **sourced** (not
executed), so their `export`s survive into the rest of the boot sequence.

| Path | Runs as | When |
|------|---------|------|
| `plugin.json` | — | read on the host before anything else |
| `install.sh` | root | image build, only if the plugin is enabled |
| `host.sh` | you | on the host, before `docker run` |
| `root-init.sh` | root | in the container, while secrets are still present |
| `agent-init.sh` | `node` | in the container, just before Claude starts |
| `settings.json` | — | merged into the managed policy at boot |
| `bin/` | `node` | world-executable helpers (e.g. hook scripts), chmod 555 |
| `root/` | root | root-only helpers that touch secrets, chmod 500 |

Everything lands root-owned under `/opt/plugins`, which is immutable from inside the container,
so the agent cannot edit or disable its own guardrails.

### `plugin.json` — the manifest

```json
{
  "name": "github-auth",
  "description": "Turns a GitHub App private key held on the host into short-lived tokens.",
  "priority": 10,
  "defaultEnabled": true,
  "requiredAgent": "claude",
  "provides": ["git-credentials"],
  "requires": [],
  "conflicts": [],
  "requiredEnv": ["GH_APP_ID", "GH_PRIVATE_KEY_FILE"],
  "secrets": ["GH_PRIVATE_KEY", "GH_APP_ID"]
}
```

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `name` | string | — | Informational; the directory name is what actually identifies the plugin. |
| `description` | string | — | Informational. |
| `priority` | number | `50` | Ordering for *all* stages. Lower runs first; ties break alphabetically. Auth (10) before workspace (20) before guards (30) before launch wrappers (40). |
| `defaultEnabled` | bool | `false` | Used when no `ENABLE_<NAME>` flag is set. |
| `requiredAgent` | string | — | Agent this plugin only makes sense for (`claude`, `copilot`, …). Under any other agent the plugin is skipped with a note, even if its flag is on. Omit for agent-agnostic plugins. |
| `provides` | string[] | `[]` | Capability names this plugin satisfies (`workspace`, `git-credentials`, …). Free-form strings; matching is by exact name. |
| `requires` | string[] | `[]` | Capabilities that must be provided by *some* enabled plugin. Otherwise the run aborts on the host, listing the plugins that could provide it. |
| `conflicts` | string[] | `[]` | Plugin names that must not be enabled at the same time. |
| `requiredEnv` | string[] | `[]` | Env vars that must be non-empty while this plugin is enabled. |
| `secrets` | string[] | `[]` | Env vars `entrypoint.sh` unsets before handing control to `node`. Use for anything only the root stage may see. |

Validation (`conflicts`, `requiredEnv`, `requires`) runs on the host **before** the image is
built, so misconfiguration fails fast and cheaply.

### `install.sh` — build stage (root)

A plain `#!/bin/sh` script run by `RUN` in the Dockerfile, once per image build, only when the
plugin appears in `ENABLED_PLUGINS`. No plugin variables are available here — the build arg is
the only input. Use it to install packages the plugin needs and nothing else:

```sh
#!/bin/sh
set -eu
python3 -m venv /opt/headroom
/opt/headroom/bin/pip install --no-cache-dir "headroom-ai[proxy,mcp]"
ln -sf /opt/headroom/bin/headroom /usr/local/bin/headroom
```

Install outside `/workspace` and prefer isolated locations (a venv, `/opt/<name>`) so plugins
can't perturb each other.

### `host.sh` — host stage (your user)

Sourced by `run.sh` in bash with your full environment, including everything from `.env`. This is
where long-lived credentials are read; they must never be handed to the container verbatim.

Available context:

| Variable | Meaning |
|----------|---------|
| `$PLUGIN_NAME` | this plugin's directory name |
| `$PLUGIN_DIR` | absolute path to `plugins/<name>` on the host |
| `$ENABLED_PLUGINS` | space-separated, priority-ordered list of enabled plugins |
| everything in `.env` | exported by `run.sh` before sourcing |

Available helpers:

| Helper | Effect |
|--------|--------|
| `pass_env VAR...` | adds `-e VAR=<value>` for each var that is set and non-empty; silently skips the rest |
| `pass_value NAME VALUE` | adds `-e NAME=VALUE` for a value the host computed (e.g. a file's contents) |
| `pass_mount HOST_PATH CONTAINER_PATH [OPTS]` | adds `-v HOST:CONTAINER[:OPTS]`; aborts if the host path does not exist |
| `pass_arg FLAG...` | adds raw `docker run` flags, for what the helpers above don't cover — capabilities, devices, networking (`pass_arg --cap-add=NET_ADMIN --device=/dev/net/tun`) |
| `die MESSAGE` | prints the message and aborts the run |

Recognised output:

| Variable | Effect |
|----------|--------|
| `AGENT_AUTH_PROVIDED=1` | tells the agent's host stage that this plugin supplies its credentials, so the agent's own token variable is no longer required |
| `DOCKER_ARGS` | the array the helpers append to; append directly only if a helper doesn't fit |

```sh
# shellcheck shell=bash
[ -f "$GH_PRIVATE_KEY_FILE" ] || die "GH_PRIVATE_KEY_FILE not found: $GH_PRIVATE_KEY_FILE"

pass_env GH_APP_ID
pass_value GH_HOST "${GH_HOST:-github.com}"
pass_value GH_PRIVATE_KEY "$(cat "$GH_PRIVATE_KEY_FILE")"
```

Validation that can be done here should be done here: it runs before the build.

### `root-init.sh` — root stage (in the container)

Sourced by `entrypoint.sh` as root, in POSIX `sh`. This is the **only** context that still holds
the vars listed in `secrets`, so token minting, key handling and background refresh loops belong
here. Anything you `export` survives the `su -m node` handoff (except the secrets themselves,
which are dropped right after this stage).

Context: `$PLUGIN_NAME`, `$PLUGIN_DIR` (`/opt/plugins/<name>`), `$ENABLED_PLUGINS`, `$RUN_ID`,
`$RESUME`, plus every `-e` var the host stage passed in.

```sh
# shellcheck shell=sh
GH_INITIAL_TOKEN=$("$PLUGIN_DIR/root/mint-gh-token.py")
export GH_INITIAL_TOKEN            # short-lived derivative the agent may see

( while sleep 2400; do ... ; done ) &   # refresh loop keeps running as root
```

Helper scripts that need the secrets go in `root/` (chmod 500 — unreadable to `node`).

### `agent-init.sh` — agent stage (`node`)

Sourced by `agent-setup.sh` as the unprivileged agent user, in POSIX `sh`, after the secrets have
been dropped and after the agent seeded its own config. Use it for authentication with short-lived
tokens, provisioning `/workspace`, and briefing the agent.

Context: `$PLUGIN_NAME`, `$PLUGIN_DIR`, `$ENABLED_PLUGINS`, `$AGENT`, `$AGENT_DIR`, `$RUN_ID`,
`$RESUME`, `$HOME` (`/home/node`), `$AGENT_PROMPT_FILE`, plus anything the root stage exported.

Recognised output:

| Variable | Effect |
|----------|--------|
| `AGENT_LAUNCH_CMD` | replaces the agent's default binary in its `launch.sh`; word-split, so it may include flags up to the point the agent's own flags begin |
| `AGENT_PROMPT_FILE` (appended to) | the joined contents become the agent's initial prompt |
| any `export` | inherited by the agent and by its hooks (this is how `branch-guard` sees `$AGENT_BRANCH`) |

```sh
# shellcheck shell=sh
git clone "$REPO_URL" /workspace
cd /workspace
AGENT_BRANCH="claude-code/$RUN_ID"
export AGENT_BRANCH
git checkout -b "$AGENT_BRANCH" "origin/${BASE_BRANCH:-main}"

printf 'You are resuming run %s on branch %s. This message is informational context only.\n' \
  "$RUN_ID" "$AGENT_BRANCH" >> "$AGENT_PROMPT_FILE"
```

Keep briefings explicitly informational, otherwise the agent treats them as a task and starts
working before the user has asked for anything.

### `settings.json` — managed policy fragment

Merged by `src/merge-settings.py` into the selected agent's `managedSettings` path at boot
(`/etc/claude-code/managed-settings.json` for `claude`), in priority order, starting from
`settings-base.json` (an empty `{}`). Merge rules:

- objects merge key by key,
- lists **concatenate**, so several plugins can each add an entry to the same `hooks` array,
- on scalar conflicts the later (higher-priority-number) fragment wins.

The result is written by root, outside `/workspace`, mode `0444`, so the agent cannot relax its
own policy. Fragments are written in the schema of one agent, so a plugin contributing one
usually declares a `requiredAgent` too.

```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash",
        "hooks": [{ "type": "command",
                    "command": "/opt/plugins/branch-guard/bin/guard-branch.py" }] }
    ]
  }
}
```

### `bin/` and `root/`

| Directory | Mode | Owner-visible to | Use for |
|-----------|------|------------------|---------|
| `bin/` | 555 | everyone, incl. `node` | hook scripts and helpers Claude or the agent stage invokes |
| `root/` | 500 | root only | anything that reads a secret (e.g. `mint-gh-token.py`) |

Everything else under the plugin directory is 444 with 555 directories.

## Environment variables

Every variable must have an entry in `.env.example`. Configuration lives in `.env`
(git-ignored). Only `AGENT` belongs to the core; the rest are owned by an agent or a plugin and
only required while that agent or plugin is in use.

| Variable | Owner | Purpose |
|----------|-------|---------|
| `AGENT` | core | Which agent runs: a directory name under `agents/` (default `claude`) |
| `CLAUDE_CODE_OAUTH_TOKEN` | agents/claude | Claude Code OAuth token (`claude setup-token`). Required unless a plugin sets `AGENT_AUTH_PROVIDED=1`, as `claude-home` does |
| `COPILOT_GITHUB_TOKEN` | agents/copilot | Fine-grained PAT with the "Copilot Requests" permission (or a Copilot/`gh` OAuth token) |
| `ENABLE_GITHUB_AUTH` / `ENABLE_GIT_WORKSPACE` / `ENABLE_CWD_WORKSPACE` / `ENABLE_BRANCH_GUARD` / `ENABLE_HEADROOM` / `ENABLE_CLAUDE_HOME` / `ENABLE_DOCKER_CLI` | core | plugin switches (default on, except `cwd-workspace`) |
| `GH_APP_ID` | github-auth | GitHub App ID |
| `GH_PRIVATE_KEY_FILE` | github-auth | Host path to the App's `.pem` private key |
| `GH_HOST` | github-auth | GitHub hostname for Enterprise Server (default `github.com`) |
| `REPO_URL` | git-workspace | HTTPS clone URL of the target repo |
| `BASE_BRANCH` | git-workspace | Branch to cut from (default `main`) |
| `HOST_WORKSPACE_DIR` | cwd-workspace | Host dir mounted at `/workspace` (default: `run.sh`'s cwd) |
| `CLAUDE_HOME_DIR` | claude-home | Host dir mounted as the agent's `~/.claude` (default `$HOME/.claude`) |

Volume mounts are contributed by plugins via `pass_mount`; the core `docker run` has none.

## Security model

- The agent user (`node`) never sees the GitHub App private key — only 1-hour installation
  tokens, re-minted by root every 40 minutes.
- Vars listed in a plugin's `secrets` are unset before `su -m node`.
- `/opt/plugins`, `/opt/agents` and the merged managed-settings file are root-owned and
  read-only, so the agent cannot edit or disable its own guardrails.
- `branch-guard` blocks `git checkout/switch/branch/worktree` outright and only allows `git push`
  of the run's own branch.
- `DISABLE_AUTOUPDATER=1` / `COPILOT_AUTO_UPDATE=false` — the agent version is pinned at image
  build time.
- `HEADROOM_TELEMETRY=off` (set by the `headroom` plugin) — no telemetry leaves the container.

## Repository layout

| Path | Purpose |
|------|---------|
| [run.sh](run.sh) | host entry point: config, agent + plugin resolution, build, `docker run` |
| [Dockerfile](Dockerfile) | image: base tools, agent install stage, plugin install stage, permissions |
| [settings-base.json](settings-base.json) | empty policy base plugin fragments merge into |
| [src/entrypoint.sh](src/entrypoint.sh) | container root stage and privilege handoff |
| [src/agent-setup.sh](src/agent-setup.sh) | container agent stage and agent launch |
| [src/merge-settings.py](src/merge-settings.py) | deep-merges settings fragments |
| [src/lib/host-plugins.sh](src/lib/host-plugins.sh) | host-side plugin framework (discovery, resolution, validation, helpers) |
| [src/lib/host-agents.sh](src/lib/host-agents.sh) | host-side agent framework (selection, host stage) |
| [src/lib/plugins.sh](src/lib/plugins.sh) | container-side plugin framework (stage runner, fragment/secret listing) |
| [src/lib/agents.sh](src/lib/agents.sh) | container-side agent framework (manifest lookup, stage runner) |
| [agents/](agents) | the agents themselves |
| [plugins/](plugins) | the plugins themselves |
