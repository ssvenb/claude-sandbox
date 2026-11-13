# claude-sandbox

A Docker sandbox for running CLI coding agents autonomously.

The core is repo- and agent-agnostic: it builds an image, starts a container, and launches the
selected agent with every permission prompt disabled. Which agent that is comes from **`AGENT`**
(see [agents/](agents)); everything opinionated — GitHub authentication, cloning a repo, pinning
the agent to a branch, mounting your `~/.claude` — lives in **plugins** that can be switched off
individually. With the defaults, the GitHub App private key never leaves your machine — tokens are
minted and refreshed on the host, and the container only sees the current short-lived installation
token — and each run works on its own
`<prefix>/<yyyymmdd>-<RUN_ID>` branch enforced by a managed hook the agent cannot edit.

## Quick start

```bash
# configuration is per-project: put it in the repo you work on, not here
cp .env.example ~/code/my-repo/.env   # pick AGENT, fill in its token and any plugin variables
cd ~/code/my-repo
./run.sh                  # build + fresh run (generates a RUN_ID)
./run.sh --resume a1b2c3  # re-attach to an existing run: its branch and its conversation
```

`jq` is required on the host. `run.sh` builds the image itself (tagged `claude-agent:$AGENT`), so
a manual `docker build -t claude-agent:claude --build-arg AGENT=claude .` is only needed if you
want to build without running.

## Web UI

```bash
mkdir -p ~/.config/claude-sandbox
printf '%s\n' ~/code/my-repo ~/code/other-repo > ~/.config/claude-sandbox/projects
./web/server.py           # http://127.0.0.1:8787  (--port N, --projects FILE, --allow-host NAME)
```

The home page is a dashboard of all your sandboxes. On top is a box to start a session by writing
its first message, with the project it is for beside it. Under it, on the left, is what is
**running now**, grouped by project: a **window** per running session (the ones waiting on your
answer first; each says what it was asked and what it is doing right now, with its pull request,
its ports and, top right, its stop button); with nothing running that side is not there, and the
projects take the width. On the right is every listed **project** with what its plugins list (its
issues), its ended sessions at the foot of its panel, a **+** button for a
new session (`run.sh --chat` in that directory) and a terminal
button (**>_**) for a shell on this machine in the project — one per project, its tab brought to
the front when it is already open. The gear button opens the project's settings, saved to its
`.claude-sandbox.json`: a form drawn from what the sandbox, each agent and each plugin declare (see
[Declaring settings](#declaring-settings)) — a switch per plugin, and per setting a toggle, text
field, number field, dropdown, list or name/value editor, with its default shown and a **reset**
that unsets it again. A filter narrows the form; the **JSON** view edits the whole file. The server
checks every declared value against its type before writing, and keeps whatever the form has no
control for; the next session reads the file.
For a project whose
`origin` is on GitHub it lists the open pull requests, with their CI status, and issues through the
host's `gh` login, each a link to its GitHub page (one tab per item, brought to the front when it
is already open); a PR on a per-run branch (`<prefix>/<date>-<RUN_ID>`) gets a **Resume** button,
which is `run.sh --resume <RUN_ID>`; an ended session in the list has one too. An issue's
**Resolve** starts a new session whose agent begins on it straight away: its first message
(`run.sh --task`) names the issue and tells it to read it with `gh issue view`, fix it with tests,
push and open a pull request that closes it. Seeing that pull request's CI through to green is
in every session's briefing (`github-auth`), not in the task.

What a project shows beyond its sessions comes from its enabled plugins, not from the web UI: the
page draws what `run.sh --web` prints for the project, which is what each enabled plugin's `web.sh`
described. `github-auth` lists the pull requests and issues, `git-workspace` recognises its per-run
branches among them, `agent-workspace` says where a run's checkout is — switch one off for a
project and its part of the page goes with it.

A session opens in a browser tab of its own, as a **chat**: your messages, the agent's answers
(markdown, streamed as it writes), what it thought, and a line per tool call that opens to show
what went in and what came back — an edit as a diff, a command with its output, a subagent with
its own calls inside. Its plan sits above the composer, a question it asks you is a card with its
choices, and the composer offers the agent's own slash commands and skills as you type `/`, its
models and effort levels, and a stop button (or **Esc**) to interrupt it. Clicking a session whose
tab is already open brings that tab to the front instead of opening a second one.

The chat is there from the first moment. While the image builds and the sandbox boots, the page
shows what the boot prints, and whatever you write is kept by the server and handed to the agent,
in order, the moment it is ready — an issue's **Resolve** is simply a session whose first message
is already written.

The agent runs behind a **chat bridge** instead of its TUI: `agents/<name>/chat.mjs`, started by
the agent's `launch.sh` when `run.sh` is given `--chat`. The bridge drives the same CLI the
terminal would, through the vendor's own SDK — the
[Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-typescript) for `claude`, the
[GitHub Copilot SDK](https://www.npmjs.com/package/@github/copilot-sdk) for `copilot` — so settings, hooks,
MCP servers, skills, slash commands and the run's conversation are the ones the terminal has, and
a run started in one can be resumed in the other. What differs per agent ends at the bridge: each
translates its SDK's messages into one set of chat events ([src/lib/chat-bridge.mjs](src/lib/chat-bridge.mjs)
lists them) on the container's stdout, and takes prompts, answers, interrupts and model changes on
its stdin, so the page knows no agent. An agent without a `chat.mjs` cannot be started with
`--chat`; `{"ui": "terminal"}` in the request that starts a session (`POST /api/sessions`) runs
its TUI in a terminal tab instead, as before.

The pages follow your browser's light or dark setting; the switch in their header pins one. They
are laid out for a phone as well as a desk: on a touch keyboard Enter starts a new line and the
button sends.

A session runs until you end it: closing its
tab, or the whole browser, leaves it running, and clicking it opens it again with the whole
conversation. Each session has two
buttons for that. **Stop** (the red square, on its window and in its tab) removes its container
and keeps it listed among its project's ended sessions, its tab showing how it ended, so you can read it and resume it with the play button. **Delete**
(the trash can, in its tab and on an ended session) stops it if it still runs, removes it from the list and closes its tabs: its
chat, VS Code and its pull request (the last two only while the page that opened them has
not been reloaded).

In a project's terminal tab, **Ctrl+C** copies the selection (and interrupts as usual when nothing is
selected), **Ctrl+Shift+C** always copies, **Ctrl+V** and **Ctrl+Shift+V** paste; where the program has taken the mouse, as the agent's
interface does, select with **Shift+drag**.

The VS Code icon in a session's tab opens VS Code in the browser on that run's checkout (the `agent-workspace`
mirror of `/workspace`), again one tab per run. It needs VS Code on the host (`code` on the PATH:
the .deb/.rpm or snap install, or the standalone CLI): the first click starts one `code serve-web`,
accepting the VS Code Server license terms on your behalf, and it stops with the web UI. Its data
(extensions, settings) lives in `~/.local/share/claude-sandbox/vscode`, with Copilot's chat
switched off (`chat.disableAIFeatures`) — the agent works in the sandbox. The first folder a
browser opens may still show the empty chat pane; close it once and VS Code keeps it closed. It listens on a unix socket only your user can reach and is served under `/vscode/` of the
web UI itself, so there is no second port to open or to forward over an SSH tunnel.

Resuming brings back the agent's conversation as well as the branch: each run's conversation is
keyed to its RUN_ID (Claude Code `--session-id`, Copilot `--name`). The transcript lives in the
agent's home directory, so it only outlives the container while `claude-home` / `copilot-home`
mounts it from the host (both on by default); without them a resumed run starts a new conversation
on the old branch.

Needs only `python3` on the host (and `gh` for the PR list); the pages load their fonts, and the
terminal page xterm.js, from a CDN.
It listens on loopback only and has no login — use an SSH tunnel to reach it from elsewhere.
Sessions belong to the server process: stopping it stops them.

## How a run boots

```
run.sh (host)
  ├─ loads the worked-on repo's config, resolves AGENT and the ENABLE_<PLUGIN> flags, validates config + capabilities
  ├─ each enabled plugin's host.sh, then the agent's host.sh, contribute `docker run` args
  ├─ mints the credentials plugins registered, mounts them at /run/credentials (ro), refreshes them in the background
  ├─ docker build --build-arg AGENT=... --build-arg ENABLED_PLUGINS=...
  └─ docker run → entrypoint.sh (root)
       ├─ chown /workspace to node
       ├─ each enabled plugin's root-init.sh (only context that holds the vars plugins declared as secrets)
       ├─ merges settings-base.json + plugin settings.json → the agent's managedSettings path (0444)
       ├─ unsets every var declared in a plugin's `secrets`, then `setpriv` to `node`
       └─ agent-setup.sh (node)
            ├─ the agent's agent-init.sh (seeds its own config for a non-interactive boot)
            ├─ each enabled plugin's agent-init.sh (auth, /workspace, guardrails, briefing)
            └─ the agent's launch.sh → $AGENT_LAUNCH_CMD + flags + [briefing]
                                       (run.sh --chat: → node chat.mjs, the agent behind its chat bridge)
```

Two variables steer the tail of that sequence:

- **`$AGENT_LAUNCH_CMD`** — how the agent binary is started; empty means the agent's own default
  (`claude`, `copilot`). An `agent-init.sh` may replace it with a wrapper.
- **`$AGENT_PROMPT_FILE`** — a temp file plugins append to during the agent stage. Its contents
  are the agent's briefing (Claude: system prompt; Copilot: first message). Stage script stdout is *not* visible to the agent, so
  anything the agent must know has to go through this file.

## Agents

Exactly one agent runs per container, chosen with `AGENT` (default `claude`). Every agent's files
ship in the image, but only the selected one's `install.sh` runs, so an unused agent's binaries
stay out of it; the image is tagged per agent, so switching back and forth doesn't rebuild.

| Agent | CLI | Credentials | Launched as |
|-------|-----|-------------|-------------|
| `claude` | Claude Code (`@anthropic-ai/claude-code`, npm) | `CLAUDE_CODE_OAUTH_TOKEN`, or the `claude-home` plugin | `claude --dangerously-skip-permissions --effort ${CLAUDE_EFFORT:-medium} [--append-system-prompt briefing]` |
| `copilot` | GitHub Copilot CLI (`@github/copilot`, npm) | `COPILOT_GITHUB_TOKEN`, or the `copilot-home` plugin | `copilot --allow-all [-i briefing]` |

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
| `chat.mjs` | `node` | in place of the agent's TUI for a web chat (`run.sh --chat`): drives the agent through its SDK and speaks the chat events of [src/lib/chat-bridge.mjs](src/lib/chat-bridge.mjs) on stdio |

`agent.json` carries `name`, `description`, `managedSettings` — the path the agent reads its
managed (enterprise) policy from, which is where plugin `settings.json` fragments are merged.
Omit it and no policy file is written. An optional `git` block names the agent in the repo, and
`git-workspace` reads it:

```json
"git": { "branchPrefix": "claude-code", "userName": "Claude Code" }
```

The branch becomes `<branchPrefix>/<yyyymmdd>-<RUN_ID>` and commits are authored under that name;
an agent that omits the block falls back to its own directory name (`copilot/20260902-1a2b3c`).
The email defaults to `<agent>@sandbox.local`. An optional `userEmail` replaces it, but GitHub
credits a commit to whichever account has registered its email, so never use an address you
don't control: `claude-code@anthropic.com` showed a stranger's account as the author of every
commit. The worked-on repo overrides the prefix, either with
`BRANCH_PREFIX` in its `.env` or — winning over that — `.plugins["git-workspace"].branchPrefix`
in its `.claude-sandbox.json`.

An optional `settings` list declares the agent's own variables (`CLAUDE_EFFORT`, its token) for
the web UI's settings form, as a plugin's do: see [Declaring settings](#declaring-settings).

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
| `ca-certs` | 1 | off | any | `ca-certs` | — | installs the host's extra root CAs (or `$CA_CERTS_DIR`) into the container trust store; sets `NODE_EXTRA_CA_CERTS` / `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` |
| `claude-home` | 5 | on | claude | `claude-home` | — | mounts the host's `~/.claude` (or `$CLAUDE_HOME_DIR`) at `/home/node/.claude`; sets `AGENT_AUTH_PROVIDED=1` |
| `copilot-home` | 5 | on | copilot | `copilot-home` | — | mounts the host's `~/.copilot` (or `$COPILOT_HOME_DIR`) at `/home/node/.copilot`; sets `AGENT_AUTH_PROVIDED=1` |
| `docker-cli` | 5 | on | any | `docker-cli` | — | Docker CLI + compose plugin install; mounts the host's `/var/run/docker.sock` |
| `netbird` | 5 | off | any | `mesh-network` | — | NetBird client install; enrols the container as its own peer (`sandbox-<RUN_ID>`) from `$NB_SETUP_KEY`, adding `NET_ADMIN` + `/dev/net/tun` |
| `github-auth` | 10 | on | any | `git-credentials` | — | `gh` CLI install; mints App installation tokens on the host as the `github-token` credential (re-minted every 40 min), `gh auth login` with each one; briefs the agent to open a pull request for its work and fix whatever fails until its CI is green |
| `gcp-auth` | 10 | off | any | `gcp-credentials` | — | Google Cloud CLI install; mints 1h service-account tokens on the host and makes them the container's ambient identity: `gcloud` reads the token file, a stand-in GCE metadata server serves the client libraries |
| `ssh-credentials` | 15 | off | any | `ssh-credentials` | — | `openssh-client` install; writes `~/.ssh/sandbox_key` + `~/.ssh/config` for the agent user |
| `upstream-proxy` | 15 | on | any | `upstream-proxy` | — | credential-injecting reverse proxies on the HOST, one per route from the project config, shared by all of a project's running sandboxes, bind-mounted as unix sockets and bridged to loopback ports that only the project's own sandboxes may use; no routes configured → does nothing |
| `git-workspace` | 20 | on | any | `workspace` | `git-credentials` | clone the `origin` remote of `run.sh`'s cwd into `/workspace`, per-run branch named after the agent (or `$BRANCH_PREFIX`) and the date, its commit identity, resume briefing |
| `cwd-workspace` | 20 | off | any | `workspace` | — | bind-mounts the host's cwd (or `$HOST_WORKSPACE_DIR`) at `/workspace`; conflicts with `git-workspace` |
| `agent-workspace` | 15 | on | any | `workspace-mirror` | — | bind-mounts `$AGENT_WORKSPACE_DIR/<project>-<date>-<RUN_ID>` (default `~/.agent-workspaces/<project>-<date>-<RUN_ID>`, created if missing) at `/workspace`, so the agent's checkout is visible on the host; removed when the container exits, unless `AGENT_WORKSPACE_CLEANUP=0`; complements `git-workspace`, conflicts with `cwd-workspace` |
| `package-managers` | 25 | on | any | `package-managers` | — | `sudo` install; lets the agent install packages itself — `npm -g`/`pip` into its home, `apt-get`/`apt` via a passwordless sudo rule (which amounts to root, so its guardrails become advisory) |
| `project-deps` | 25 | on | any | `project-deps` | — | installs the dependencies the target repo declares in the project config: apt/npm/pip packages (as root, at boot) and `setup` shell commands (as the agent user, in the provisioned `/workspace`); nothing configured → does nothing |
| `dev-server` | 28 | on | any | `dev-server` | — | starts the project's server (`.plugins["dev-server"].command`) in `/workspace` at every boot, after `project-deps`; the agent restarts it with `bin/sandbox-server`. Its ports are published when listed in `PORTS`, see [Published ports](#published-ports); nothing configured → does nothing |
| `branch-guard` | 30 | on | claude | — | `workspace` | `guard-branch.py` PreToolUse hook |

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
| `web.sh` | you | on the host, by `run.sh --web`, whenever the web UI draws the project |
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
  "name": "netbird",
  "description": "Enrolls the container as its own NetBird peer, so the agent reaches a private mesh network without the host's peer or the NetBird PAT ever entering the sandbox.",
  "priority": 5,
  "defaultEnabled": false,
  "provides": ["mesh-network"],
  "requires": [],
  "requiredEnv": ["NB_SETUP_KEY"],
  "secrets": ["NB_SETUP_KEY"]
}
```

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `name` | string | — | Informational; the directory name is what actually identifies the plugin. |
| `description` | string | — | Informational. |
| `priority` | number | `50` | Ordering for *all* stages. Lower runs first; ties break alphabetically. Auth (10) before workspace (20) before guards (30) before launch wrappers (40). |
| `defaultEnabled` | bool | `false` | Used when no `ENABLE_<NAME>` flag is set. |
| `requiredAgent` | string | — | Agent this plugin only makes sense for (`claude`, `copilot`, …). Under any other agent the plugin is skipped silently, even if its flag is on. Omit for agent-agnostic plugins. |
| `provides` | string[] | `[]` | Capability names this plugin satisfies (`workspace`, `git-credentials`, …). Free-form strings; matching is by exact name. |
| `requires` | string[] | `[]` | Capabilities that must be provided by *some* enabled plugin. Otherwise the run aborts on the host, listing the plugins that could provide it. |
| `conflicts` | string[] | `[]` | Plugin names that must not be enabled at the same time. |
| `requiredEnv` | string[] | `[]` | Env vars that must be non-empty while this plugin is enabled. |
| `secrets` | string[] | `[]` | Env vars `entrypoint.sh` unsets before handing control to `node`. Use for anything only the root stage may see. |
| `settings` | object[] | `[]` | The settings this plugin reads, for the web UI's settings form. See [Declaring settings](#declaring-settings). |

Validation (`conflicts`, `requiredEnv`, `requires`) runs on the host **before** the image is
built, so misconfiguration fails fast and cheaply.

### Declaring settings

Every setting a project can make in its `.claude-sandbox.json` is declared by its owner — a plugin
in its `plugin.json`, an agent in its `agent.json`, the sandbox itself in
[src/kernel.json](src/kernel.json) — as a `settings` list. The web UI draws its settings form from
these, and `web/server.py` checks values against them before it writes the file.

```json
"settings": [
  { "key": "branchPrefix", "type": "string", "label": "Branch prefix",
    "description": "Leading segment of each run's branch.", "placeholder": "claude-code" },
  { "env": "AGENT_WORKSPACE_CLEANUP", "type": "boolean", "label": "Delete the mirror on exit", "default": true }
]
```

Each entry names exactly one of `key` (a key in the plugin's own section,
`.plugins["<plugin>"].<key>`, read with `plugin_config`) or `env` (a variable in the `env` block,
which must also be in `.env.example`; there a boolean is written as `1`/`0`). The rest:

| Key | Meaning |
|-----|---------|
| `type` | `boolean` (a switch), `string`, `path` (a text field), `text` (several lines), `integer` (with optional `min`/`max`), `enum` (a dropdown of `choices`), `list` (of `items`, itself a type: a list of enums is a set of checkboxes), `map` (name → value pairs), `object` (its own `fields`), `json` (anything, edited as JSON) |
| `label`, `description` | What the form shows. |
| `default` | What applies while it is unset; shown as the placeholder or the switch's resting state. Informational: the owner still applies its own default. |
| `placeholder` | An example value, for settings without a fixed default. |
| `required` | The value must be set (inside an `object`; a plugin's `requiredEnv` is marked as well). |
| `secret` | A password field. The file is plain text, so prefer the repo's `.env` for secrets. |
| `pattern` | A regular expression a string must match whole. |
| `monospace` | Draw the field in a fixed-width font (commands, paths). |
| `when` | Inside an `object`: show (and check) the field only while a sibling has one of these values, e.g. `{"type": ["header", "bearer"]}`. |
| `title` | On a list's `object` items: the field whose value titles each item. |

`tests/test_manifests.py` keeps the declarations in step with `.env.example`: every sandbox
variable but the `ENABLE_` flags and the two `PROJECT_*_FILE` paths is declared exactly once.

### `install.sh` — build stage (root)

A plain `#!/bin/sh` script run by `RUN` in the Dockerfile, once per image build, only when the
plugin appears in `ENABLED_PLUGINS`. No plugin variables are available here — the build arg is
the only input. Use it to install packages the plugin needs and nothing else:

```sh
#!/bin/sh
set -eu
python3 -m venv /opt/mytool
/opt/mytool/bin/pip install --no-cache-dir mytool
ln -sf /opt/mytool/bin/mytool /usr/local/bin/mytool
```

Install outside `/workspace` and prefer isolated locations (a venv, `/opt/<name>`) so plugins
can't perturb each other.

### `host.sh` — host stage (your user)

Sourced by `run.sh` in bash with your full environment, including the worked-on repo's settings. This is
where long-lived credentials are read; they must never be handed to the container verbatim.

Available context:

| Variable | Meaning |
|----------|---------|
| `$PLUGIN_NAME` | this plugin's directory name |
| `$PLUGIN_DIR` | absolute path to `plugins/<name>` on the host |
| `$ENABLED_PLUGINS` | space-separated, priority-ordered list of enabled plugins |
| sandbox-owned settings | exported by `run.sh` from the worked-on repo's `.env` / `.claude-sandbox.json` |

Available helpers:

| Helper | Effect |
|--------|--------|
| `pass_env VAR...` | adds `-e VAR=<value>` for each var that is set and non-empty; silently skips the rest |
| `pass_value NAME VALUE` | adds `-e NAME=VALUE` for a value the host computed (e.g. a file's contents) |
| `pass_mount HOST_PATH CONTAINER_PATH [OPTS]` | adds `-v HOST:CONTAINER[:OPTS]`; aborts if the host path does not exist |
| `pass_arg FLAG...` | adds raw `docker run` flags, for what the helpers above don't cover — capabilities, devices, networking (`pass_arg --cap-add=NET_ADMIN --device=/dev/net/tun`) |
| `register_credential NAME INTERVAL FUNCTION` | a short-lived credential minted on the host: the core calls the shell function `FUNCTION` (which prints the credential) once every host stage has run, then every `INTERVAL` seconds (≥ 60), and keeps the result at `/run/credentials/NAME` in the container (see below) |
| `die MESSAGE` | prints the message and aborts the run |
| `plugin_config FILTER [DEFAULT]` | a scalar from this plugin's section of the project config file (see below) |
| `plugin_config_json FILTER [DEFAULT]` | the same, as raw JSON, for objects and arrays |

Recognised output:

| Variable | Effect |
|----------|--------|
| `AGENT_AUTH_PROVIDED=1` | tells the agent's host stage that this plugin supplies its credentials, so the agent's own token variable is no longer required |
| `DOCKER_ARGS` | the array the helpers append to; append directly only if a helper doesn't fit |

```sh
# shellcheck shell=bash
[ -f "$GH_PRIVATE_KEY_FILE" ] || die "GH_PRIVATE_KEY_FILE not found: $GH_PRIVATE_KEY_FILE"

GITHUB_AUTH_DIR=$PLUGIN_DIR   # $PLUGIN_DIR is gone by the time the function runs
github_auth_mint() {
  GH_APP_ID="$GH_APP_ID" GH_PRIVATE_KEY_FILE="$GH_PRIVATE_KEY_FILE" REPO_URL="${REPO_URL:-}" \
    "$GITHUB_AUTH_DIR/host/mint-gh-token.py"
}
register_credential github-token 2400 github_auth_mint
pass_value GH_HOST "${GH_HOST:-github.com}"
```

Validation that can be done here should be done here: it runs before the build.

#### Short-lived credentials

A token derived from something long-lived — an App private key, your own cloud login — is minted
on the host, never in the container: `register_credential` hands the core a function that prints
it, and `src/lib/host-credentials.sh` does the rest for every plugin alike.

- **First mint** after every plugin's (and the agent's) host stage, so the function may use what a
  later plugin set — `github-auth` picks the installation that owns git-workspace's `REPO_URL`. A
  failure, or empty output, aborts the run with the function's stderr, before the image is built.
- **Refresh** every `INTERVAL` seconds in the background for as long as `run.sh` runs. The deadline
  is wall-clock, checked once a minute, so a suspended host re-mints as soon as it wakes instead of
  sleeping past the expiry. A failed refresh keeps the previous credential and retries a minute
  later; each attempt goes to the refresh log `run.sh` names at startup, not to the agent's terminal.
- **Delivery:** one file per credential in a directory only your user can reach on the host,
  mounted read-only at `/run/credentials`. Each refresh replaces the file atomically. Read it when
  you need it, or watch it — `github-auth`'s `agent-init.sh` re-runs `gh auth login` whenever its
  token changes; a copy taken at boot goes stale.

Pick an interval comfortably inside the credential's lifetime (GitHub's 1h tokens: 40 minutes), so
a few failed attempts in a row still don't let it lapse.

### `web.sh` — web stage (your user)

Sourced by `run.sh --web`, which the web UI runs in a project to learn what to draw for it. The
agent and the plugins are resolved exactly as for a run — same project settings, same `ENABLE_*`
switches — but nothing is validated, built or started, so keep it quick and never `die` over
something a run would need. The web UI itself knows nothing about any plugin: it draws what these
calls describe.

The page has two places for what a plugin shows: **sections** of the project's panel (pull
requests, issues, …) and a **session's window**, where an item is a small
button with its status mark and `ref` that opens its `url` in a tab of its own (a run's pull
request, with its CI). An item is `{title, url}` plus optional `ref` (a short id shown first,
`#12`), `note` (`Draft`), `status` (`ok`, `fail` or `pending`: a mark before it, e.g. CI) with its
`status_text`, and any field a later plugin may read.

| Call | Puts on the page |
|------|------------------|
| `web_list TITLE JSON_ARRAY` | a section of items; an item's `start` (`{label, task}`) is a button starting a session on `task`, e.g. an issue's Resolve |
| `web_run_items JSON_ARRAY` | items shown only for the run a later plugin ties them to (`web_tie_items`): on that run's session row while one is listed; with none, an item naming a `section` (`Pull requests`, for a run's open one) shows under that title on the project's panel with a **Resume** button, any other nowhere. An item's `on_delete` (`{ask, action, arg}`) offers to tidy it up when its run's session is deleted (close the pull request) |
| `web_session_item RUN_ID JSON_ITEM` | an item on that run's session row, shown while the page lists a session of the run |
| `web_tie_items JQ_FILTER` | hands items listed so far (by plugins of a lower `priority`) to the run the filter names for each (a RUN_ID; `null` or `""` leaves the item be): such an item moves onto that run's session row while one is listed, else stays in its section with a **Resume** button |
| `web_map_items JQ_FILTER` | rewrites every item listed so far (by plugins of a lower `priority`) |
| `web_live_items FILE` | items from a JSON array in FILE, each with its `run_id`, on the row of that run's running session; the server re-reads the file on every poll, so it suits what comes and goes within seconds (a port a session's server publishes, see [Published ports](#published-ports)); `{host}` in a `url` stands for the host name the page was opened by |
| `web_note TEXT` | one line saying why there is nothing to list |
| `web_checkout GLOB` | where a run's `/workspace` is on this machine, `{run_id}` standing for the run; adds the VS Code button to its session |

```bash
# plugins/github-auth/web.sh lists the pull requests, with their CI and `branch`, as a section;
# plugins/git-workspace/web.sh, which owns the branch naming, then ties its own to their runs:
web_tie_items 'if (.branch // "") | test("^.+/[0-9]{8}-[0-9a-f]{6}$") then .branch[-6:] else null end'
```

### Project configuration — `.claude-sandbox.json`

The sandbox's own directory holds no configuration — its `.env` is never read. Settings that
belong to the *repo the agent works on* — which
upstreams to proxy, which hosts a key is for — live in an optional `.claude-sandbox.json` in the
directory you launched `run.sh` from (`$HOST_CWD`), so a checkout can carry its own sandbox
configuration. `PROJECT_CONFIG_FILE` points somewhere else.

```json
{
  "plugins": {
    "upstream-proxy": {
      "envFile": ".env",
      "routes": [ { "name": "azure-openai", "port": 8082, "upstream": "${AZURE_OPENAI_ENDPOINT}" } ]
    },
    "project-deps": {
      "apt": ["ripgrep"],
      "npm": ["pnpm@9"],
      "pip": ["ruff"],
      "setup": ["make bootstrap"]
    }
  }
}
```

A `host.sh` reads its own section — `.plugins["<this plugin>"]` — with `plugin_config` (scalars)
and `plugin_config_json` (objects and arrays); both take a jq filter relative to that section and
a fallback used when the file, the section or the key is missing:

```sh
# shellcheck shell=bash
ROUTES=$(plugin_config_json '.routes' '[]')
ENV_FILE=$(plugin_config '.envFile' ".env")
```

Both the file and every key in it are optional, so a plugin that reads config must still work
without one. Nothing in the file reaches the container by itself — the plugin decides what
crosses over, via `pass_*`. See [.claude-sandbox.example.json](.claude-sandbox.example.json).

### Google Cloud through `gcp-auth`

For a service account that is already scoped to what the sandbox may do, `gcp-auth` makes it the
container's own Google identity, so `gcloud` and every Google client library work unmodified —
real endpoints, real TLS, no emulator variables:

```json
{ "env": { "GCP_SERVICE_ACCOUNT": "sandbox-reader@my-project.iam.gserviceaccount.com" },
  "plugins": { "gcp-auth": { "enabled": true } } }
```

`run.sh` mints a 1-hour token for the account with your own gcloud login (you need
`roles/iam.serviceAccountTokenCreator` on it) and re-mints it every 40 minutes as the `gcp-token`
credential. In the container, `gcloud` reads that file on every call, and a root-owned stand-in
for the GCE metadata server hands it to the client libraries, which find it through
`GCE_METADATA_HOST` as they would on a VM. It listens on a free loopback port and answers only the
container's own processes. The agent holds the current
token, usable from anywhere until it expires, but never anything it could mint a new one from; what
it can do is decided by the account's IAM roles alone. For per-method/path restrictions on top,
use the proxy route below instead.

### Scoped GCP access through `upstream-proxy`

A route with `"auth": {"type": "gcp"}` gives the agent Google Cloud access without a single
credential entering the container. The host proxy mints the token itself, running
`gcloud auth print-access-token --impersonate-service-account=<serviceAccount>` on your own
login, caches it, and re-mints it before it expires, so long runs keep working. Access is narrowed
in three places:

1. **IAM:** a dedicated service account holding only what the sandbox may do, e.g.
   `roles/storage.objectViewer` on one bucket (bucket-level binding, not project-level). Your host
   identity needs `roles/iam.serviceAccountTokenCreator` on it.
2. **`accessBoundary`** (optional, Cloud Storage only): a
   [Credential Access Boundary](https://cloud.google.com/iam/docs/downscoping-short-lived-credentials)
   the proxy exchanges the token through at `sts.googleapis.com`, downscoping it to the listed
   buckets/prefixes/roles.
3. **`allowMethods` / `allowPaths`:** the proxy refuses anything else with 403 before it reaches
   Google, e.g. only `GET`/`HEAD` on `/storage/v1/b/my-bucket/o` and `/download/storage/v1/b/my-bucket/o`.
   Both are optional on every route: left out, the route relays every method and every path.

In the container, `STORAGE_EMULATOR_HOST` points the Python/Go/Node storage clients at the proxy
(unauthenticated, which is what you want: the proxy adds the credential), and
`CLOUDSDK_API_ENDPOINT_OVERRIDES_STORAGE` does the same for `gcloud storage`; plain `curl
http://127.0.0.1:<port>/storage/v1/b/my-bucket/o` works too. A bad login or a missing grant fails
`run.sh` at startup. See the `gcs` route in [.claude-sandbox.example.json](.claude-sandbox.example.json).

Sandboxes of the same project — launched from the same checkout, with the same routes and env
file — share one host proxy: the first `run.sh` starts it, later ones reuse it, and the
last one to exit stops it. It loads its credentials once, at start, so a rotated key in the env
file takes effect only once no sandbox of the project is running.

### Published ports

Part of the core, not a plugin. Each sandbox has a network namespace of its own, so two sessions
can both run a server on `:3000`. Which ports a sandbox opens is a setting, `PORTS`: a
space-separated list, usually kept with the project in `.claude-sandbox.json` (the gear on the
dashboard edits its `env` block):

```json
{ "env": { "PORTS": "3000 5173" } }
```

Nothing else is published, and the dashboard shows nothing else; with `PORTS` unset a sandbox
opens no ports at all, and no proxy is started for it. Inside the container a root helper
(`src/publish-ports.py`, started by `entrypoint.sh`) notices when a non-root process listens on one
of those ports — on any address, `127.0.0.1` included — and offers it as a unix socket in a
directory mounted from the host, under a root-only `/run/ports` the agent cannot reach. One central
proxy on your machine (`src/portd.py`, managed by `src/lib/host-ports.sh`), shared by every sandbox
of every project, gives each such port a port of its own on `$PORTS_BIND` (default `127.0.0.1`):
the same number while it is free, otherwise any free one, and the same one again when that
session's server restarts. The first `run.sh` starts the proxy; it exits once no `run.sh` using it
is alive. The web UI shows each published port as a button on its session's row, within a second
or two of the server starting. The agent's briefing names the configured ports, so it serves on
one of them.

The `dev-server` plugin starts the project's server at every boot, in `/workspace` after
`project-deps`; the agent controls it with `/opt/plugins/dev-server/bin/sandbox-server
start|stop|restart|status|log`:

```json
{ "env": { "PORTS": "3000" }, "plugins": { "dev-server": { "command": "pnpm dev --port 3000" } } }
```

The host's own services are at `host.docker.internal` from inside, if they listen on an address
other than loopback; the host's `localhost` is out of the agent's reach. Unix sockets created in a
container are reachable from the host with Docker Engine on Linux, not through Docker Desktop's VM.

### The worked-on repo's `.env`

Some of those per-project settings conventionally live in the repo's own `.env` instead
(`BRANCH_PREFIX`, say). `run.sh` loads `$HOST_CWD/.env` centrally — `PROJECT_ENV_FILE` points
somewhere else, `/dev/null` loads nothing — and any `host.sh` reads a single key from it:

```sh
# shellcheck shell=bash
PREFIX=$(project_env BRANCH_PREFIX "${BRANCH_PREFIX:-}")
```

The file is *scanned*, not sourced: it is the target repo's, full of its own secrets and possibly
its own commands, so nothing in it lands in `run.sh`'s environment and nothing reaches the
container except through the plugin's own `pass_*` calls.

### `root-init.sh` — root stage (in the container)

Sourced by `entrypoint.sh` as root, in POSIX `sh`. This is the **only** context that still holds
the vars listed in `secrets` — for a secret that has to enter the container as is, like netbird's
setup key, which only root may use. Anything derived from a long-lived credential is minted on the
host instead (`register_credential`). Anything you `export` survives the `setpriv` handoff to
`node` (except the secrets themselves, which are dropped right after this stage).

Context: `$PLUGIN_NAME`, `$PLUGIN_DIR` (`/opt/plugins/<name>`), `$ENABLED_PLUGINS`, `$RUN_ID`,
`$RESUME`, plus every `-e` var the host stage passed in.

```sh
# shellcheck shell=sh
netbird up --setup-key "$NB_SETUP_KEY" ...   # dropped from the environment right after this stage
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
| `AGENT_PROMPT_FILE` (appended to) | the joined contents become the agent's briefing (system prompt for Claude, first message for Copilot) |
| any `export` | inherited by the agent and by its hooks (this is how `branch-guard` sees `$AGENT_BRANCH`) |

```sh
# shellcheck shell=sh
git clone "$REPO_URL" /workspace
cd /workspace
AGENT_BRANCH="$AGENT_BRANCH_PREFIX/$(date -u +%Y%m%d)-$RUN_ID"
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
| `root/` | 500 | root only | anything that reads a secret or must not be replaced by `node` (e.g. upstream-proxy's `forward.py`) |

Everything else under the plugin directory is 444 with 555 directories.

## Environment variables

Every variable must have an entry in `.env.example`, which doubles as the allowlist of
sandbox-owned names. Configuration is per-project: it lives in the worked-on repo's `.env` /
`.claude-sandbox.json`, never in the sandbox's own directory. Only `AGENT` belongs to the core; the rest are owned by an agent or a plugin and
only required while that agent or plugin is in use.

| Variable | Owner | Purpose |
|----------|-------|---------|
| `AGENT` | core | Which agent runs: a directory name under `agents/` (default `claude`) |
| `PROJECT_CONFIG_FILE` | core | Per-project plugin configuration (default `$HOST_CWD/.claude-sandbox.json`; optional) |
| `PROJECT_ENV_FILE` | core | The worked-on repo's `.env`, scanned for plugin settings it keeps there (default `$HOST_CWD/.env`; `/dev/null` loads nothing) |
| `PORTS` | core | Space-separated ports a sandbox opens: published on the host, and shown on the dashboard, while something in it listens on them (default: none) |
| `PORTS_BIND` | core | Address the central port proxy publishes the sandboxes' ports on (default `127.0.0.1`; `0.0.0.0` for your whole network) |
| `CLAUDE_CODE_OAUTH_TOKEN` | agents/claude | Claude Code OAuth token (`claude setup-token`). Required unless a plugin sets `AGENT_AUTH_PROVIDED=1`, as `claude-home` does |
| `CLAUDE_EFFORT` | agents/claude | Reasoning effort Claude Code runs at: `low`, `medium` (the sandbox default), `high`, `xhigh`, `max` |
| `COPILOT_GITHUB_TOKEN` | agents/copilot | Fine-grained PAT with the "Copilot Requests" permission (or a Copilot/`gh` OAuth token). Required unless a plugin sets `AGENT_AUTH_PROVIDED=1`, as `copilot-home` does |
| `ENABLE_GITHUB_AUTH` / `ENABLE_GIT_WORKSPACE` / `ENABLE_CWD_WORKSPACE` / `ENABLE_AGENT_WORKSPACE` / `ENABLE_BRANCH_GUARD` / `ENABLE_CLAUDE_HOME` / `ENABLE_COPILOT_HOME` / `ENABLE_DOCKER_CLI` / `ENABLE_CA_CERTS` / `ENABLE_DEV_SERVER` / `ENABLE_UPSTREAM_PROXY` / `ENABLE_PROJECT_DEPS` / `ENABLE_NETBIRD` / `ENABLE_GCP_AUTH` / `ENABLE_SSH_CREDENTIALS` | core | plugin switches (default on, except `ca-certs`, `cwd-workspace`, `gcp-auth`, `netbird` and `ssh-credentials`) |
| `GH_APP_ID` | github-auth | GitHub App ID |
| `GH_PRIVATE_KEY_FILE` | github-auth | Host path to the App's `.pem` private key |
| `GH_HOST` | github-auth | GitHub hostname for Enterprise Server (default `github.com`) |
| `GH_USERNAME` | github-auth | Username git and `gh` authenticate as with the installation token (default: the App's bot login) |
| `BASE_BRANCH` | git-workspace | Branch to cut from (default: the repo's own default branch, via `origin/HEAD`) |
| `HOST_WORKSPACE_DIR` | cwd-workspace | Host dir mounted at `/workspace` (default: `run.sh`'s cwd) |
| `BRANCH_PREFIX` | git-workspace | Leading segment of the per-run branch name, read from the **worked-on repo's** `$HOST_CWD/.env` (not the sandbox's); `.plugins["git-workspace"].branchPrefix` in its `.claude-sandbox.json` wins over it, and with neither it defaults to the agent manifest's `branchPrefix`, else the agent's directory name |
| `AGENT_WORKSPACE_DIR` | agent-workspace | Host dir holding the per-run mirrors of `/workspace`, created if missing (default: `$HOME/.agent-workspaces`; each run uses `<dir>/<project>-<date>-<RUN_ID>`) |
| `AGENT_WORKSPACE_CLEANUP` | agent-workspace | Delete the run's mirror directory when the container exits; 0 keeps it for inspection, at one leftover directory per run (default: 1) |
| `CA_CERTS_DIR` | ca-certs | Host dir holding extra root certificates, PEM or DER (default `/usr/local/share/ca-certificates`) |
| `CLAUDE_HOME_DIR` | claude-home | Host dir mounted as the agent's `~/.claude` (default `$HOME/.claude`) |
| `COPILOT_HOME_DIR` | copilot-home | Host dir mounted as the agent's `~/.copilot` (default `$HOME/.copilot`) |

Volume mounts are contributed by plugins via `pass_mount`; the core `docker run` has none.

## Security model

- The GitHub App private key never enters the container, not even as root — the host mints the
  1-hour installation tokens and re-mints them every 40 minutes; the container only reads the
  current one from `/run/credentials`.
- Vars listed in a plugin's `secrets` are unset before the `setpriv` handoff to `node`.
- `/opt/plugins`, `/opt/agents` and the merged managed-settings file are root-owned and
  read-only, so the agent cannot edit or disable its own guardrails.
- `branch-guard` blocks `git checkout/switch/branch/worktree` outright and only allows `git push`
  of the run's own branch.
- `DISABLE_AUTOUPDATER=1` / `COPILOT_AUTO_UPDATE=false` — the agent version is pinned at image
  build time.

## Repository layout

| Path | Purpose |
|------|---------|
| [run.sh](run.sh) | host entry point: config, agent + plugin resolution, build, `docker run` |
| [web/](web) | web UI over `run.sh`: `server.py` (sessions in ptys, PRs and issues, a tunnel to `code serve-web`), the status page `index.html` and the per-session terminal `session.html` |
| [Dockerfile](Dockerfile) | image: base tools, agent install stage, plugin install stage, permissions |
| [settings-base.json](settings-base.json) | empty policy base plugin fragments merge into |
| [src/kernel.json](src/kernel.json) | the sandbox's own settings (`AGENT`, ports), declared as plugins declare theirs |
| [src/entrypoint.sh](src/entrypoint.sh) | container root stage and privilege handoff |
| [src/agent-setup.sh](src/agent-setup.sh) | container agent stage and agent launch |
| [src/merge-settings.py](src/merge-settings.py) | deep-merges settings fragments |
| [src/lib/host-plugins.sh](src/lib/host-plugins.sh) | host-side plugin framework (discovery, resolution, validation, helpers) |
| [src/lib/host-agents.sh](src/lib/host-agents.sh) | host-side agent framework (selection, host stage) |
| [src/lib/host-project-config.sh](src/lib/host-project-config.sh) | per-project plugin configuration (`.claude-sandbox.json`, `plugin_config`) |
| [src/lib/plugins.sh](src/lib/plugins.sh) | container-side plugin framework (stage runner, fragment/secret listing) |
| [src/lib/agents.sh](src/lib/agents.sh) | container-side agent framework (manifest lookup, stage runner) |
| [agents/](agents) | the agents themselves |
| [plugins/](plugins) | the plugins themselves |
| [tests/](tests) | pytest suite; `tests/e2e` boots the built image |
