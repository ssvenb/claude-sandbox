# claude-sandbox

A Docker sandbox for running Claude Code agents autonomously.

The core is repo-agnostic: it builds an image, starts a container, and launches `claude
--dangerously-skip-permissions`. Everything opinionated — GitHub authentication, cloning a repo,
pinning the agent to a branch, mounting your `~/.claude` — lives in **plugins** that can be
switched off individually. With the default plugins on, the GitHub App private key never leaves
your machine (the container only sees short-lived installation tokens), and each run works on its
own `claude-code/<RUN_ID>` branch enforced by a managed hook the agent cannot edit.

## Quick start

```bash
cp .env.example .env      # fill in CLAUDE_CODE_OAUTH_TOKEN and any plugin variables
./run.sh                  # build + fresh run (generates a RUN_ID)
./run.sh --resume a1b2c3  # re-attach to an existing run's branch
```

`jq` is required on the host. `run.sh` builds the image itself, so a manual
`docker build -t claude-agent .` is only needed if you want to build without running.

## How a run boots

```
run.sh (host)
  ├─ sources .env, resolves ENABLE_<PLUGIN> flags, validates config + capabilities
  ├─ each enabled plugin's host.sh contributes `docker run` args (secrets stay on the host)
  ├─ docker build --build-arg ENABLED_PLUGINS=...   (only enabled plugins' install.sh run)
  └─ docker run → entrypoint.sh (root)
       ├─ chown /workspace to node
       ├─ each enabled plugin's root-init.sh (only context that holds secrets)
       ├─ merges settings-base.json + plugin settings.json → /etc/claude-code/managed-settings.json (0444)
       ├─ unsets every var declared in a plugin's `secrets`, then `su -m node`
       └─ agent-setup.sh (node)
            ├─ each enabled plugin's agent-init.sh (auth, /workspace, guardrails, briefing)
            ├─ seeds ~/.claude.json for a non-interactive boot
            └─ $AGENT_LAUNCH_CMD --dangerously-skip-permissions [briefing]
```

Two variables steer the tail of that sequence:

- **`$AGENT_LAUNCH_CMD`** — how Claude is started; defaults to `claude`. An `agent-init.sh` may
  replace it with a wrapper (the `headroom` plugin sets `headroom wrap claude --no-serena --`).
- **`$AGENT_PROMPT_FILE`** — a temp file plugins append to during the agent stage. Its contents
  become Claude's initial prompt. Stage script stdout is *not* visible to the agent, so anything
  the agent must know has to go through this file.

## Plugins

All plugins ship in the image; `ENABLE_<NAME>` flags in `.env` decide which ones run. The flag
name uppercases the directory name and turns `-` into `_` (`github-auth` → `ENABLE_GITHUB_AUTH`);
an unset flag falls back to the manifest's `defaultEnabled`. Accepted values are
`1|true|yes|on` / `0|false|no|off`; anything else aborts the run.

`run.sh` passes the resolved set to `docker build` as the `ENABLED_PLUGINS` build arg, so only
enabled plugins' `install.sh` execute and a disabled plugin's dependencies stay out of the image
— changing the mix means the next `./run.sh` rebuilds those layers.

| Plugin | Priority | Default | Provides | Requires | Owns |
|--------|---------:|---------|----------|----------|------|
| `claude-home` | 5 | on | `claude-home` | — | mounts the host's `~/.claude` (or `$CLAUDE_HOME_DIR`) at `/home/node/.claude`; sets `CLAUDE_AUTH_PROVIDED=1` |
| `docker-cli` | 5 | on | `docker-cli` | — | Docker CLI + compose plugin install; mounts the host's `/var/run/docker.sock` |
| `github-auth` | 10 | on | `git-credentials` | — | `gh` CLI install, App token minting + 40-min refresh loop, `gh auth login` |
| `git-workspace` | 20 | on | `workspace` | `git-credentials` | clone into `/workspace`, per-run branch, resume briefing |
| `cwd-workspace` | 20 | off | `workspace` | — | bind-mounts the host's cwd (or `$HOST_WORKSPACE_DIR`) at `/workspace`; conflicts with `git-workspace` |
| `branch-guard` | 30 | on | — | `workspace` | `guard-branch.py` PreToolUse hook |
| `headroom` | 40 | on | `llm-proxy` | — | wraps the launch command in the headroom compression proxy (`headroom-ai[proxy,mcp]` in `/opt/headroom`) |

Disable them all and the agent starts plain `claude` in an empty `/workspace` with no GitHub
access.

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
| `die MESSAGE` | prints the message and aborts the run |

Recognised output:

| Variable | Effect |
|----------|--------|
| `CLAUDE_AUTH_PROVIDED=1` | tells the core this plugin supplies Claude credentials, so `CLAUDE_CODE_OAUTH_TOKEN` is no longer required |
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
been dropped. Use it for authentication with short-lived tokens, provisioning `/workspace`, and
briefing the agent.

Context: `$PLUGIN_NAME`, `$PLUGIN_DIR`, `$ENABLED_PLUGINS`, `$RUN_ID`, `$RESUME`, `$HOME`
(`/home/node`), `$AGENT_PROMPT_FILE`, plus anything the root stage exported.

Recognised output:

| Variable | Effect |
|----------|--------|
| `AGENT_LAUNCH_CMD` | replaces `claude` as the launch command; word-split, so it may include flags up to the point Claude's own flags begin |
| `AGENT_PROMPT_FILE` (appended to) | the joined contents become Claude's initial prompt |
| any `export` | inherited by Claude and by its hooks (this is how `branch-guard` sees `$AGENT_BRANCH`) |

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

Merged by `src/merge-settings.py` into `/etc/claude-code/managed-settings.json` at boot, in
priority order, starting from `settings-base.json` (an empty `{}`). Merge rules:

- objects merge key by key,
- lists **concatenate**, so several plugins can each add an entry to the same `hooks` array,
- on scalar conflicts the later (higher-priority-number) fragment wins.

The result is written by root, outside `/workspace`, mode `0444`, so the agent cannot relax its
own policy.

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
(git-ignored). Only `CLAUDE_CODE_OAUTH_TOKEN` belongs to the core; the rest are owned by a
plugin and only required while that plugin is enabled.

| Variable | Owner | Purpose |
|----------|-------|---------|
| `CLAUDE_CODE_OAUTH_TOKEN` | core | Claude Code OAuth token (`claude setup-token`). Required unless a plugin sets `CLAUDE_AUTH_PROVIDED=1`, as `claude-home` does |
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
- `/opt/plugins` and `/etc/claude-code/managed-settings.json` are root-owned and read-only, so
  the agent cannot edit or disable its own guardrails.
- `branch-guard` blocks `git checkout/switch/branch/worktree` outright and only allows `git push`
  of the run's own branch.
- `DISABLE_AUTOUPDATER=1` — the Claude Code version is pinned at image build time.
- `HEADROOM_TELEMETRY=off` (set by the `headroom` plugin) — no telemetry leaves the container.

## Repository layout

| Path | Purpose |
|------|---------|
| [run.sh](run.sh) | host entry point: config, plugin resolution, build, `docker run` |
| [Dockerfile](Dockerfile) | image: base tools, Claude Code, plugin install stage, permissions |
| [settings-base.json](settings-base.json) | empty policy base plugin fragments merge into |
| [src/entrypoint.sh](src/entrypoint.sh) | container root stage and privilege handoff |
| [src/agent-setup.sh](src/agent-setup.sh) | container agent stage and Claude launch |
| [src/merge-settings.py](src/merge-settings.py) | deep-merges settings fragments |
| [src/lib/host-plugins.sh](src/lib/host-plugins.sh) | host-side plugin framework (discovery, resolution, validation, helpers) |
| [src/lib/plugins.sh](src/lib/plugins.sh) | container-side plugin framework (stage runner, fragment/secret listing) |
| [plugins/](plugins) | the plugins themselves |
