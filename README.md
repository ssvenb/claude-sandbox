# claude-sandbox

A Docker sandbox for running CLI coding agents autonomously.

The core is repo- and agent-agnostic: it builds an image, starts a container, and launches the
selected agent with every permission prompt disabled. Which agent that is comes from **`AGENT`**
(see [agents/](agents)); everything opinionated — GitHub authentication, cloning a repo, pinning
the agent to a branch, mounting your `~/.claude` — lives in **plugins** that can be switched off
individually. With the defaults, the GitHub App private key never leaves your machine — tokens are
minted and refreshed on the host, and the container only sees the current short-lived installation
token — and each run works on its own
`<prefix>/<yyyymmdd>-<RUN_ID>` branch kept by a managed hook — a guardrail: everything inside the container is the agent's, and only what crosses to the host is a boundary (see [Security model](#security-model)).

## Quick start

```bash
./install.sh              # once: checks the host, creates the uv environment, builds the web UI,
                          # links `claude-sandbox` and `claude-sandbox-web` into ~/.local/bin
# a project is a file: ~/.config/claude-sandbox/projects/<name>.json, its repo (a git URL or a
# path on this machine) and its settings (.env.example lists them, the web UI's gear edits the
# file). No .env is read.
echo '{"repo": "https://github.com/me/my-repo", "env": {"GH_AUTH": "coder"}}' \
  > ~/.config/claude-sandbox/projects/my-repo.json   # see "Authentications"
claude-sandbox --project my-repo                   # build + fresh run (generates a RUN_ID); the same as <checkout>/run.sh
claude-sandbox --project my-repo --resume a1b2c3   # re-attach to an existing run: its branch and its conversation
```

The host needs Docker, `git`, `jq` and [uv](https://docs.astral.sh/uv/) (which brings Python),
plus Node 20.19+ to build the web UI. `./install.sh` checks for each, offers to install what your
package manager has (`--yes`: without asking) and uv itself, and is safe to run again;
`--no-web` sets up `run.sh` alone, `--dev` adds the test tools, `--project DIR` configures DIR as a
project (`<its name>.json`, unless there is one), `--bind HOST` has the systemd service listen on HOST (a VPN name, say) rather than
loopback. `run.sh` builds the image itself (tagged `claude-agent:$AGENT`), so
a manual `docker build -t claude-agent:claude --build-arg AGENT=claude .` is only needed if you
want to build without running.

## Web UI

```bash
./install.sh --project ~/code/my-repo --project ~/code/other-repo   # builds the UI, configures the projects
claude-sandbox-web        # http://127.0.0.1:8787  (--port N, --projects DIR, --allow-host NAME)
```

The projects are the `<name>.json` files in `~/.config/claude-sandbox/projects`. `claude-sandbox-web` is
`src/server/serve.sh`, the server (`src/server/server.py`) in the uv environment.

The server has no login of its own. To open it beyond this machine, put Google sign-in in front of
it with `src/server/serve-oauth.sh`, which runs the server on `127.0.0.1:8786` (`SANDBOX_WEB_UPSTREAM_PORT`)
and [oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/) (installed separately) on `0.0.0.0:4180`.
Only accounts of one email domain get through:

```bash
export OAUTH2_PROXY_CLIENT_ID=... OAUTH2_PROXY_CLIENT_SECRET=... \
       OAUTH2_PROXY_COOKIE_SECRET=$(openssl rand -hex 16)
src/server/serve-oauth.sh --host box.example.com [--port 4180] [--domain levatioai.com] [-- oauth2-proxy flag...]
```

The OAuth client is a Google Cloud *Web application* client with the redirect URI
`https://<host>/oauth2/callback`. Create it in the Console (Google Auth Platform → Clients): Google has
no API, and so no Terraform resource, for these clients. A consent screen of type **Internal** also
keeps out every account outside the Workspace. oauth2-proxy sets its cookie `Secure`, so serve it over
HTTPS: run it behind a TLS proxy, or pass `-- --https-address=:443 --tls-cert-file=... --tls-key-file=...`.
Ports that sessions publish (see [Published ports](#published-ports)) do not go through the proxy.

The home page is a dashboard of all your sandboxes. On top is a box to start a session by writing
its first message, with the project it is for beside it. Under it, on the left, is what is
**running now**, grouped by project: a **window** per running session (the ones waiting on your
answer first; each says what it was asked and what it is doing right now, with its pull request,
its ports and, top right, its stop button); with nothing running that side is not there, and the
projects take the width. On the right is every listed **project** with what its plugins list (its
issues), its ended sessions at the foot of its panel, a **+** button for a
new session (`run.sh --project <name> --chat`). There is no shell on this machine: the server
runs as you, so one would be your account to anyone who reaches the page. The gear button opens the project's settings, saved to its
file (its repo among them): a form drawn from what the sandbox, each agent and each plugin declare (see
[Declaring settings](#declaring-settings)) — a switch per plugin, and per setting a toggle, text
field, number field, dropdown, list or name/value editor, with its default shown and a **reset**
that unsets it again. A filter narrows the form; the **JSON** view edits the whole file. The server
checks every declared value against its type before writing, and keeps whatever the form has no
control for; the next session reads the file.
The menu (**⋯**, top right) has the sandbox's own **Settings**: the projects, added (a name and its
repo) and deleted (its file only, refused while it has sessions) at once, and your
[authentications](#authentications--configclaude-sandboxauthjson) as the same form — an entry each,
its fields those of its type — or JSON, saved readable by you alone. Agents add to the menu too:
Claude's **Sign in to Claude** runs `claude auth login` on the server (its `~/.claude`, which
`claude-home` mounts): a new tab goes on to claude.com's sign-in, and the code that page ends on,
pasted into the dialog on the dashboard, signs it in (see an agent's [`signIn`](#agents)).
When the server's Claude is signed out (`claude auth status` fails, checked as the dashboard loads
and each time it comes back into view), the dashboard asks whether to sign in again; **Not now**
holds until it is seen signed in once more.
For a project whose
`origin` is on GitHub it lists the open pull requests, with their CI status, and issues with a token of
the project's GitHub App (`GH_AUTH`, which the plugin requires; the App needs read access to issues, checks and commit statuses, and
write to pull requests to close one), each a link to its GitHub page (one tab per item, brought to the front when it
is already open); a PR on a per-run branch (`<prefix>/<date>-<RUN_ID>`) gets a **Resume** button,
which is `run.sh --resume <RUN_ID>`; an ended session in the list has one too. An issue's
**Resolve** starts a new session whose agent begins on it straight away: its first message
(`run.sh --task`) names the issue and tells it to read it with `gh issue view`, fix it with tests,
push and open a pull request that closes it. Seeing that pull request's CI through to green is
in every session's briefing (`github-auth`), not in the task.

What a project shows beyond its sessions comes from its enabled plugins, not from the web UI: the
page draws what `run.sh --web` prints for the project, which is what each enabled plugin's `web.sh`
described. `github-auth` lists the pull requests and issues, `git-workspace` recognises its per-run
branches among them and lists the files a run changed (left of its chat on a wide screen, behind a
button in its header on a narrow one), `agent-workspace` says where a run's checkout is — switch one off for a
project and its part of the page goes with it.

A session opens in a browser tab of its own, as a **chat**: your messages, the agent's answers
(markdown, streamed as it writes), what it thought, and a line per tool call that opens to show
what went in and what came back — an edit as a diff, a command with its output, a subagent with
its own calls inside. Its plan sits above the composer, a question it asks you is a card with its
choices, and the composer offers the agent's own slash commands and skills as you type `/`, its
models and effort levels, and a stop button (or **Esc**) to interrupt it. Clicking a session whose
tab is already open brings that tab to the front instead of opening a second one.

Right of the chat are its **side chats**: questions about the conversation, asked while the agent
works on, which it never hears of. Each is a tab with a conversation of its own (ask again in it,
or open another): with every question it is given what the run's conversation said since its last
one, it may read the files, and it changes nothing. They are kept with the session and come back
with a resumed run. An agent's bridge says whether it takes them — Claude's does, Copilot's not
yet. On a wide screen the changed files and the side chats are panels on either side of the chat:
drag a panel's edge (or focus it and use the arrow keys) to size it, double-click the edge for its
first width, and put it away with the button at its end of the header; the browser remembers both.
On a narrow one each opens over the chat from its button.

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
translates its SDK's messages into one set of chat events ([src/services/chat/chat-bridge.mjs](src/services/chat/chat-bridge.mjs)
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

In a terminal tab (an agent's TUI, `"ui": "terminal"`), **Ctrl+C** copies the selection (and interrupts as usual when nothing is
selected), **Ctrl+Shift+C** always copies, **Ctrl+V** and **Ctrl+Shift+V** paste; where the program has taken the mouse, as the agent's
interface does, select with **Shift+drag**.

The VS Code icon in a session's tab opens VS Code in the browser on that run's checkout (the `agent-workspace`
mirror of `/workspace`), again one tab per run. It needs VS Code on the host (`code` on the PATH:
the .deb/.rpm or snap install, or the standalone CLI): the first click starts one `code serve-web`,
accepting the VS Code Server license terms on your behalf, and it stops with the web UI. Its data
(extensions, settings) lives in `~/.local/share/claude-sandbox/vscode`, with Copilot's chat
switched off (`chat.disableAIFeatures`) — the agent works in the sandbox. The first folder a
browser opens may still show the empty chat pane; close it once and VS Code keeps it closed. The
checkout is the agent's, so it opens in restricted mode without asking to trust it: tasks, debug
configs and the risky part of its `.vscode/settings.json` stay off, as they would otherwise run as you on this
machine. Trusting it is still possible, under **Restricted Mode** in the status bar; don't, and
don't run `git` or an editor of your own in the mirror either. It listens on a unix socket only your user can reach and is served under `/plugins/agent-workspace/` of the
web UI itself, so there is no second port to open or to forward over an SSH tunnel.

Resuming brings back the agent's conversation as well as the branch: each run's conversation is
keyed to its RUN_ID (Claude Code `--session-id`, Copilot `--name`). The transcript lives in the
agent's home directory, so it only outlives the container while `claude-home` (the run's copy) / `copilot-home`
mounts it from the host (both on by default); without them a resumed run starts a new conversation
on the old branch.

The server needs only `python3` and [uv](https://docs.astral.sh/uv/) on the host; `gh` is not needed. The pages are one
[React](https://react.dev) app in TypeScript, [web](web), built with [Vite](https://vite.dev)
(Node 20 or later, with npm) into `web/dist`, which the server hands out: `./install.sh` builds
it, as does `npm ci && npm run build` in `web`; until it is built the pages answer 503 and say
so. The app picks its page by the address — `/` the dashboard, `/chat#<id>` a session's
conversation, `/session#<id>` a terminal — and is grouped into `src/pages` (the three), `src/components`
(by feature: `dashboard`, `chat`, `settings`, `terminal`, and `common` for what they share),
`src/hooks` (the event stream, polling, the theme, …), `src/api` (typed calls to `/api/*` and the
shapes of what comes back), `src/lib` (what is not React: a conversation built from its events,
tabs, diffs) and `src/styles`. A session's page loads its own part only where there is one: the
chat its markdown ([react-markdown](https://github.com/remarkjs/react-markdown), never as HTML) and
diffs ([jsdiff](https://github.com/kpdecker/jsdiff)), the terminal [xterm.js](https://xtermjs.org),
all bundled; only the fonts come from a CDN. To work on it, run the server and `npm run dev` in
`web`, which serves the pages with hot reload and passes `/api` on to the server on port 8787.
It listens on loopback only and has no login — use an SSH tunnel to reach it from elsewhere.
Sessions outlive the server: each runs under `src/server/holder.py`, which keeps its output while no server
listens, and the next server takes them back from `~/.local/state/claude-sandbox/sessions`, running or
ended, so a restart (the dashboard's update button, say) cuts nothing off. Under systemd each holder
runs in a scope of its own (`systemd-run --user --scope`), outside the server unit's cgroup.

## How a run boots

```
run.sh (host: src/orchestrator, Python)
  ├─ loads the worked-on repo's config, resolves AGENT and the ENABLE_<PLUGIN> flags, validates config + capabilities
  ├─ src/contract/host/stage.sh (one bash, alive until the container is gone; its exit hooks run then)
  │    ├─ each enabled plugin's host.sh, then the agent's host.sh, contribute `docker run` args
  │    └─ mints the credentials plugins registered, mounts them at /run/credentials (ro), refreshes them in the background
  ├─ docker build --build-arg AGENT=... --build-arg ENABLED_PLUGINS=...
  └─ docker run → entrypoint.sh (root)
       ├─ chown /workspace to node
       ├─ each enabled plugin's root-init.sh (setup that needs root: trust store, dockerd, packages)
       ├─ merges settings-base.json + plugin settings.json → the agent's managedSettings path (0444)
       ├─ `setpriv` to `node`
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
| `claude` | Claude Code (`@anthropic-ai/claude-code`, npm) | a `claude-token` authentication named by `CLAUDE_AUTH`, or the `claude-home` plugin | `claude --dangerously-skip-permissions --effort ${CLAUDE_EFFORT:-medium} [--append-system-prompt briefing]` |
| `copilot` | GitHub Copilot CLI (`@github/copilot`, npm) | a `copilot-token` authentication named by `COPILOT_AUTH`, or the `copilot-home` plugin | `copilot --allow-all [-i briefing]` |

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
| `web/index.tsx` | your browser | the agent's own part of the web UI, bundled with it when it is built: its items in the dashboard's menu |
| `chat.mjs` | `node` | in place of the agent's TUI for a web chat (`run.sh --chat`): drives the agent through its SDK and speaks the chat events of [src/services/chat/chat-bridge.mjs](src/services/chat/chat-bridge.mjs) on stdio |

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
commit. The worked-on repo overrides the prefix with `.plugins["git-workspace"].branchPrefix`
in its project file.

An optional `settings` list declares the agent's own variables (`CLAUDE_EFFORT`, its token) for
the web UI's settings form, as a plugin's do: see [Declaring settings](#declaring-settings).

An optional `signIn` is the command that signs the agent's CLI on the host in again, as the web
server's user: it prints a link to sign in at, then reads the code that page ends on from stdin
(`["claude", "auth", "login"]`). The server runs it from its PATH or `~/.local/bin`; the dashboard's
menu offers it when the agent's `web/index.tsx` puts a `SignInButton`
([web/src/components/common/SignInButton.tsx](web/src/components/common/SignInButton.tsx)) in its
`Menu` (see [web/src/plugins.ts](web/src/plugins.ts)'s `AgentUI`): `GET /api/agents/<name>/sign-in`
starts the command and redirects to its link, `POST` with `{"code": …}` hands it the code.
An optional `signedIn` is a command that exits 0 while the CLI is signed in
(`["claude", "auth", "status"]`): with it, `GET /api/agents/<name>/signed-in` answers
`{"signedIn": …}`, and the `SignInButton` asks to sign in again when it is not.

Because `host.sh` runs after the plugin host stage, it can see `AGENT_AUTH_PROVIDED=1` from a
plugin that supplies credentials itself and skip its own token check:

```sh
# shellcheck shell=bash
[ "${AGENT_AUTH_PROVIDED:-0}" = 1 ] || : "${CLAUDE_CODE_OAUTH_TOKEN:?must be set}"
pass_env CLAUDE_CODE_OAUTH_TOKEN
```

## Plugins

All plugins ship in the image; a project's file decides which ones run
(`.plugins["<name>"].enabled`, or an `ENABLE_<NAME>` flag in its `env` block). The flag
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
| `claude-home` | 5 | on | claude | `claude-home` | — | mounts a copy of the host's `~/.claude` (or `$CLAUDE_HOME_DIR`) at `/home/node/.claude`: the run's own, at `~/.local/state/claude-sandbox/claude-home/<RUN_ID>`, taken afresh at every start without your projects' conversations (`/workspace`'s memory included), and cut back to the run's conversation when it exits. Only a login the run refreshed goes back to yours, so hooks or settings the agent writes never run on this machine; sets `AGENT_AUTH_PROVIDED=1` |
| `copilot-home` | 5 | on | copilot | `copilot-home` | — | mounts a copy of the host's `~/.copilot` (or `$COPILOT_HOME_DIR`) at `/home/node/.copilot`: the run's own, at `~/.local/state/claude-sandbox/copilot-home/<RUN_ID>`, taken afresh at every start but for the run's sessions (`session-state/`), cut back to those when it exits; nothing goes back to yours; sets `AGENT_AUTH_PROVIDED=1` |
| `docker-cli` | 5 | on | any | `docker-cli` | — | Docker Engine, CLI, compose and buildx install; runs the sandbox under the host's [Sysbox](https://github.com/nestybox/sysbox) runtime (`--runtime=sysbox-runc`, refuses to start without it) and starts a Docker daemon of its own inside, so the agent sees neither the host's containers nor another sandbox's |
| `netbird` | 5 | off | any | `mesh-network` | — | NetBird client install; enrols the container as its own peer (`sandbox-<RUN_ID>`) from the `netbird-setup-key` authentication `NB_AUTH` names, adding `NET_ADMIN` + `/dev/net/tun` |
| `ports` | 5 | on | any | `ports` | — | publishes the ports listed in `PORTS`: joins the central port proxy on the HOST, shared by every sandbox of every project, and offers what the agent listens on as unix sockets in a directory mounted from it; see [Published ports](#published-ports); nothing listed → does nothing |
| `github-auth` | 10 | on | any | `git-credentials` | — | `gh` CLI install; mints App installation tokens on the host as the `github-token` credential (re-minted every 40 min), `gh auth login` with each one; briefs the agent to open a pull request for its work and fix whatever fails until its CI is green |
| `gcp-auth` | 10 | off | any | `gcp-credentials` | — | Google Cloud CLI install; mints 1h service-account tokens on the host and makes them the container's ambient identity: `gcloud` reads the token file, a stand-in GCE metadata server serves the client libraries |
| `ssh-credentials` | 15 | off | any | `ssh-credentials` | — | `openssh-client` install; writes `~/.ssh/sandbox_key` + `~/.ssh/config` for the agent user |
| `upstream-proxy` | 15 | on | any | `upstream-proxy` | — | credential-injecting reverse proxies on the HOST, one per route from the project config, shared by all of a project's running sandboxes, bind-mounted (read-only) as unix sockets and bridged to loopback ports; no routes configured → does nothing |
| `pr-review` | 25 | off | any | — | `git-credentials` | has the web UI start a review session for a run's pull request once its CI is green and the run's session is deleted, under another GitHub App (`.plugins["pr-review"].auth`), with guardrails against what the pull request says; see [Reviewing pull requests](#reviewing-pull-requests-with-pr-review) |
| `git-workspace` | 20 | on | any | `workspace` | `git-credentials` | clone the `origin` remote of `run.sh`'s cwd into `/workspace`, per-run branch named after the agent (or `$BRANCH_PREFIX`) and the date, its commit identity, resume briefing |
| `cwd-workspace` | 20 | off | any | `workspace` | — | bind-mounts the host's cwd (or `$HOST_WORKSPACE_DIR`) at `/workspace`; conflicts with `git-workspace` |
| `agent-workspace` | 15 | on | any | `workspace-mirror` | — | bind-mounts `$AGENT_WORKSPACE_DIR/<project>-<date>-<RUN_ID>` (default `~/.agent-workspaces/<project>-<date>-<RUN_ID>`, created if missing) at `/workspace`, so the agent's checkout is visible on the host; removed when the container exits, unless `AGENT_WORKSPACE_CLEANUP=0`; complements `git-workspace`, conflicts with `cwd-workspace` |
| `package-managers` | 25 | on | any | `package-managers` | — | lets the agent install packages itself, without root or `sudo` — `npm -g`/`pip` into its home, and `apt-home <pkg>...`, which downloads Debian packages with the dependencies the image lacks and unpacks them into `~/.local` (on `PATH` and `LD_LIBRARY_PATH`) without running their maintainer scripts |
| `project-deps` | 25 | on | any | `project-deps` | — | installs the dependencies the target repo declares in the project config: apt/npm/pip packages (as root, at boot) and `setup` shell commands (as the agent user, in the provisioned `/workspace`); nothing configured → does nothing |
| `dev-server` | 28 | on | any | `dev-server` | — | starts the project's server (`.plugins["dev-server"].command`) in `/workspace` at every boot, after `project-deps`; the agent restarts it with `bin/sandbox-server`. Its ports are published when listed in `PORTS` (the `ports` plugin), see [Published ports](#published-ports); nothing configured → does nothing |
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
| `web/index.tsx` | your browser | the plugin's own part of the web UI, bundled with it when it is built (see [`web.sh`](#websh--web-stage-your-user)) |
| `root-init.sh` | root | in the container, for setup that needs root |
| `agent-init.sh` | `node` | in the container, just before Claude starts |
| `settings.json` | — | merged into the managed policy at boot |
| `bin/` | `node` | world-executable helpers (hook scripts, the agent stage's daemons), chmod 555 |

Everything lands root-owned and read-only under `/opt/plugins`, so the agent does not edit its
guardrails by accident. Guardrails only: the agent can be root in its container (the `docker`
group), so nothing in the image holds against it.

### `plugin.json` — the manifest

```json
{
  "name": "netbird",
  "description": "Enrolls the container as its own NetBird peer, so the agent reaches a private mesh network without the host's peer or the NetBird PAT ever entering the sandbox.",
  "priority": 5,
  "defaultEnabled": false,
  "provides": ["mesh-network"],
  "requires": [],
  "requiredEnv": ["NB_AUTH"]
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
| `settings` | object[] | `[]` | The settings this plugin reads, for the web UI's settings form. See [Declaring settings](#declaring-settings). |

Validation (`conflicts`, `requiredEnv`, `requires`) runs on the host **before** the image is
built, so misconfiguration fails fast and cheaply.

### Declaring settings

Every setting a project can make in its file is declared by its owner — a plugin
in its `plugin.json`, an agent in its `agent.json`, the sandbox itself in
[src/orchestrator/kernel.json](src/orchestrator/kernel.json) — as a `settings` list. The web UI draws its settings form from
these, and `src/server/server.py` checks values against them before it writes the file.

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
| `type` | `boolean` (a switch), `string`, `path` (a text field), `text` (several lines), `integer` (with optional `min`/`max`), `enum` (a dropdown of `choices`), `list` (of `items`, itself a type: a list of enums is a set of checkboxes), `map` (name → value pairs), `object` (its own `fields`), `json` (anything, edited as JSON), `auth` (the name of one of your [authentications](#authentications--configclaude-sandboxauthjson) of the type(s) its `auth` names: a dropdown of those configured, see there) |
| `label`, `description` | What the form shows. |
| `default` | What applies while it is unset; shown as the placeholder or the switch's resting state. Informational: the owner still applies its own default. |
| `placeholder` | An example value, for settings without a fixed default. |
| `required` | The value must be set (inside an `object`; a plugin's `requiredEnv` is marked as well). |
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

Sourced in bash (`src/contract/host/stage.sh`, which `run.sh` starts once it has resolved the run) with
your full environment, including the worked-on repo's settings. Every enabled plugin's `host.sh`
and then the agent's are sourced into that one shell, so a variable one sets is seen by the next,
and what one exports reaches `docker` too. The shell lives until the container is gone, which is
when the `on_exit` hooks run. This is where long-lived credentials are read; they must never be
handed to the container verbatim.

Available context:

| Variable | Meaning |
|----------|---------|
| `$PLUGIN_NAME` | this plugin's directory name |
| `$PLUGIN_DIR` | absolute path to `plugins/<name>` on the host |
| `$ENABLED_PLUGINS` | space-separated, priority-ordered list of enabled plugins |
| sandbox-owned settings | exported by `run.sh` from the project's file (and your shell) |

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
# GH_APP_ID and GH_PRIVATE_KEY_FILE are filled from the authentication GH_AUTH names.
[ -f "$GH_PRIVATE_KEY_FILE" ] || die "github-auth: the App's privateKeyFile is not there: $GH_PRIVATE_KEY_FILE"

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
it, and `src/services/credentials/credentials.sh` does the rest for every plugin alike.

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
| `web_poll SECONDS` | nothing: has the server describe the project at least this often, page or no page (see [Watching and starting](#watching-and-starting-web_poll-web_start)) |
| `web_start JSON` | nothing: a session the server starts by itself, once per `key`, removed when its agent has finished |
| `web_on_status CMD [ARG]…` | nothing: a command the server runs on this machine each time one of the project's sessions changes status as its dot shows it (idle with background tasks running counts as working), with `{project, run_id, session, url, status, before}` as JSON on stdin; `url` is the session's page, a status is `starting`, `working`, `idle`, `question` or `null` once it ended (agent-status posts its webhook from it) |
| `web_checkout GLOB` | where a run's `/workspace` is on this machine, `{run_id}` standing for the run: its session's `workspace` |
| `web_command NAME CMD [ARG]…` | a command the server runs in a run's checkout (see `web_checkout`), with the run's id in `WEB_RUN_ID`, when the plugin's page code asks (`GET /api/sessions/<id>/plugins/<plugin>/<NAME>`); the JSON it prints is the answer. The checkout is the agent's, `.git/config` included: run git there through `docker exec … sandbox-$WEB_RUN_ID`, never on this machine |
| `web_server CMD [ARG]…` | an HTTP server of the plugin's, started on the first request under `/plugins/<plugin>/` and handed every such request (WebSockets too), behind the web UI's own guard; one for all projects, listening on the unix socket `$WEB_SOCKET` under the base path `$WEB_BASE` |

Anything else a plugin draws itself, in `plugins/<name>/web/index.tsx`: React, typechecked and
bundled with the page, reaching the page's own modules as `@ui/…`. Its default export fills the
places [`web/src/plugins.ts`](web/src/plugins.ts) offers (on a session's chat page: beside its
state, with its buttons, and a side panel), and it is drawn only for projects that enable the
plugin. git-workspace lists a run's changed files that way (`web_command changes`), and
agent-workspace opens its checkout in VS Code (`web_server`).

```bash
# plugins/github-auth/web.sh lists the pull requests, with their CI and `branch`, as a section;
# plugins/git-workspace/web.sh, which owns the branch naming, then ties its own to their runs:
web_tie_items 'if (.branch // "") | test("^.+/[0-9]{8}-[0-9a-f]{6}$") then .branch[-6:] else null end'
```

### Project configuration — `~/.config/claude-sandbox/projects/<name>.json`

The sandbox's own directory holds no configuration, and no `.env` is read — neither the
sandbox's nor the worked-on repo's: a project's file is the one place its settings are made (its
`env` block for the variables [.env.example](.env.example) lists, a section per plugin for the
rest), over what your shell exports. The file's name is the project's (`run.sh --project
<name>`), and its `repo` the repo the agent works on: a path on this machine, or a git URL. Plugins
see a path as `$HOST_CWD`; a git URL is not cloned on this machine at all: `$HOST_CWD` is empty,
`$REPO_URL` is the URL, and git-workspace clones it in the container with the project's
credentials (so a private repo needs only its `GH_AUTH` App). `cwd-workspace` and relative
`data-mounts` paths need a checkout here, and refuse a URL. Without `--project`, `run.sh` works on the directory it was
started in, with no project file (`PROJECT_CONFIG_FILE` names one).

```json
{
  "repo": "https://github.com/me/my-repo",
  "plugins": {
    "upstream-proxy": {
      "routes": [ { "name": "azure-openai", "port": 8082, "upstream": "${AZURE_OPENAI_ENDPOINT}",
                    "auth": { "credential": "azure-openai", "header": "api-key" } } ]
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
PREFIX=$(plugin_config '.branchPrefix' "")
```

Both the file and every key in it are optional, so a plugin that reads config must still work
without one. Nothing in the file reaches the container by itself — the plugin decides what
crosses over, via `pass_*`. See [.claude-sandbox.example.json](.claude-sandbox.example.json).

### Google Cloud through `gcp-auth`

For a service account that is already scoped to what the sandbox may do, `gcp-auth` makes it the
container's own Google identity, so `gcloud` and every Google client library work unmodified —
real endpoints, real TLS, no emulator variables:

```json
{ "env": { "GCP_AUTH": "data" }, "plugins": { "gcp-auth": { "enabled": true } } }
```

where `data` is a `gcp-service-account` of your authentications. `run.sh` mints a 1-hour token for
its account with your application default credentials (`gcloud auth application-default login`,
once; you need `roles/iam.serviceAccountTokenCreator` on it) and re-mints it every 40 minutes as the `gcp-token`
credential. In the container, `gcloud` reads that file on every call, and a stand-in
for the GCE metadata server hands it to the client libraries, which find it through
`GCE_METADATA_HOST` as they would on a VM. It listens on a free loopback port. The agent holds the current
token, usable from anywhere until it expires, but never anything it could mint a new one from; what
it can do is decided by the account's IAM roles alone. For per-method/path restrictions on top,
use the proxy route below instead.

### Credentials of `upstream-proxy` routes

A route's `auth.credential` names one of your [authentications](#authentications--configclaude-sandboxauthjson),
and its type says how the proxy authenticates with it:

| Type | Sent as |
|------|---------|
| `api-key` (a model provider's key, say) | `Authorization: Bearer <key>` (OpenAI and most others), or as it is in the header `auth.header` names (`x-api-key` for Anthropic, `api-key` for Azure OpenAI) |
| `oauth2-client` | `Authorization: Bearer <token>`, a client-credentials token from its `tokenUrl` (with its `audience`), cached until a minute before it expires |
| `gcp-service-account` | `Authorization: Bearer <token>`, minted with your application default credentials for its `serviceAccount` (none: your own account), see below |

```json
{ "name": "azure-openai", "port": 8082, "upstream": "https://my-resource.openai.azure.com",
  "auth": { "credential": "azure-openai", "header": "api-key" },
  "containerEnv": { "AZURE_OPENAI_ENDPOINT": "http://127.0.0.1:8082", "AZURE_OPENAI_API_KEY": "proxied-on-the-host" } }
```

The credential stays in the host proxy, which reads it from the file itself, again on every
request: the agent's SDK gets a placeholder and the loopback address. A name the file lacks, one
of another type, or a file others can read fails `run.sh` at startup. No credential named: the
route adds none.

### Scoped GCP access through `upstream-proxy`

A route whose `auth.credential` is a `gcp-service-account` gives the agent Google Cloud access
without a single credential entering the container. The host proxy mints the token itself, impersonating
`<serviceAccount>` with your application default credentials (google-auth), caches it, and re-mints it before it expires, so long runs keep working. Access is narrowed
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
last one to exit stops it. It loads the env file once, at start, so a rotated key there takes
effect only once no sandbox of the project is running; a named credential is read on every request.

### Published ports

The `ports` plugin (on by default). Each sandbox has a network namespace of its own, so two sessions
can both run a server on `:3000`. Which ports a sandbox opens is a setting, `PORTS`: a
space-separated list, usually kept in the project's file (the gear on the
dashboard edits its `env` block):

```json
{ "env": { "PORTS": "3000 5173" } }
```

Nothing else is published, and the dashboard shows nothing else; with `PORTS` unset a sandbox
opens no ports at all, and no proxy is started for it. Inside the container a helper
(`plugins/ports/bin/publish-ports.py`, started by its `agent-init.sh`) notices when a process listens on one
of those ports — on any address, `127.0.0.1` included — and offers it as a unix socket in a
directory mounted from the host, `/run/ports/sockets`. That directory is the agent's to write, so the
proxy on the host trusts nothing in it: it publishes only the ports the run's `PORTS` lists (which it
learns from `run.sh`, not from the container), and opens each socket anew, never through a symlink,
on every connection. One central
proxy on your machine (`plugins/ports/host/portd.py`, joined and left through `host/lease.py` by its `host.sh`),
shared by every sandbox of every project, gives each such port a port of its own on `$PORTS_BIND`
(default: the address the web UI listens on, which `src/server/server.py` exports as `SANDBOX_WEB_BIND`
for every run it starts; `127.0.0.1` for a run started from a terminal):
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

### Authentications — `~/.config/claude-sandbox/auth.json`

The identities a sandbox may act as — a GitHub App, a Google Cloud service account — are
configured once, on your machine, outside every project (`SANDBOX_AUTH_FILE` points somewhere
else), each under a name:

```json
{
  "coder":    {"type": "github-app", "appId": "123456", "privateKeyFile": "~/keys/coder.pem"},
  "reviewer": {"type": "github-app", "appId": "234567", "privateKeyFile": "~/keys/reviewer.pem"},
  "data":     {"type": "gcp-service-account", "serviceAccount": "sandbox@my-project.iam.gserviceaccount.com"},
  "openai":   {"type": "api-key", "key": "sk-…"}
}
```

| Type | Named by | Fields |
|------|----------|--------|
| `github-app` | `GH_AUTH` (`github-auth`), `.plugins["pr-review"].auth` | `appId`, `privateKeyFile`; optional `host` (GitHub Enterprise Server), `username` (what git and `gh` in the container authenticate as; default: the App's bot) |
| `gcp-service-account` | `GCP_AUTH` (`gcp-auth`), a route's `auth.credential` (`upstream-proxy`) | `serviceAccount`; optional `project`, `credentialFile` (a workload identity federation config, used instead of your application default credentials) |
| `api-key` | a route's `auth.credential` (`upstream-proxy`) | `key` |
| `oauth2-client` | a route's `auth.credential` (`upstream-proxy`) | `tokenUrl`, `clientId`, `clientSecret`; optional `audience` |
| `netbird-setup-key` | `NB_AUTH` (`netbird`) | `key`; optional `managementUrl` (a self-hosted server) |
| `ssh-key` | `SSH_AUTH` (`ssh-credentials`) | `privateKeyFile` (no passphrase); optional `user`, `knownHostsFile` |
| `claude-token` | `CLAUDE_AUTH` (agent `claude`) | `token`, from `claude setup-token` |
| `copilot-token` | `COPILOT_AUTH` (agent `copilot`) | `token`: a fine-grained PAT with "Copilot Requests", or a Copilot/`gh` OAuth token |

This file is the only place a key, a token or an identity is configured: no plugin or agent has a
setting for one, and a project only names an entry — in the settings form, a dropdown of those of
the right type (names only; what they hold reaches the page only in the menu's Settings, which edits this file). A single run may name another
(`run.sh --set GH_AUTH=reviewer`, which is how `pr-review` reviews under another App than the one
that wrote the pull request). The file must be readable by you alone (`chmod 600`), or nothing
uses it. Nothing of it reaches the container but what a plugin hands over: GitHub and Google
tokens are minted on the host, and `upstream-proxy` keeps its credentials in its host process.

The core (`src/orchestrator/auth.py`) knows the types, no provider. A plugin or an agent declares a
setting of type `auth` naming the type it takes, and which of its own variables each field of the
entry fills; its stages then read those variables as before, and no project can set them itself
(they are not in `.env.example`):

```json
{"env": "GH_AUTH", "type": "auth", "auth": "github-app", "label": "GitHub App",
 "fills": {"appId": "GH_APP_ID", "privateKeyFile": "GH_PRIVATE_KEY_FILE", "host": "GH_HOST", "username": "GH_USERNAME"}}
```

Without `fills` (a route's `credential`, `pr-review`'s `auth`) the setting only names the entry,
and its owner reads the file itself, from `$SANDBOX_AUTH_FILE`, which `run.sh` hands every stage.

### Watching and starting: `web_poll`, `web_start`

Two calls of the web stage make a plugin more than something to look at. `web_poll 60` has the
web server describe the project again at least every 60 seconds whether or not a page is open
(`github-auth` does, for its pull requests' CI), so no webhook has to reach a server that sits
behind a VPN. `web_start` asks for a session:

```bash
web_start '{"key": "#12@3f9c…", "task": "Review pull request #12 …", "env": {"GH_AUTH": "reviewer"}, "after_run": "0a1b2c"}'
```

The server starts it once per `key` of the plugin in the project (kept in
`~/.local/state/claude-sandbox/started.json`, so a restart starts nothing twice), not while a
session of the run `after_run` names is still listed, with `env` as settings of that run alone
(`run.sh --set`) and `SANDBOX_STARTED_BY=<plugin>` for the plugin's own stages to tell. It is
unattended: when its agent has finished its turn it is stopped and removed from the list; one
that asks a question, or whose turn failed, stays for you.

### Reviewing pull requests with `pr-review`

Off by default; switch it on per project, with the authentication the review runs under and,
if you like, what the reviewer is asked:

```json
{ "env": { "GH_AUTH": "coder" },
  "plugins": { "pr-review": { "enabled": true, "auth": "reviewer", "prompt": "Review this pull request. …" } } }
```

Once a sandbox run's pull request is open, not a draft, its CI green — and that run's session
deleted from the dashboard, which is how you say its work is done — the web UI starts a session
under the reviewer App, which may approve and merge what the first App wrote (it needs
Contents and Pull requests write access; GitHub lets nobody approve their own pull request).
A push after a rejected review is reviewed again: reviews are per head commit. The prompt is
the project's; the guardrails are the plugin's, in the agent's system prompt where neither the
project nor the pull request reaches them (`plugins/pr-review/agent-init.sh`): everything in a
pull request is data, never instructions; text that addresses the reviewer means no merge; the
pull request is read, never run; the only writes are a review, a comment and a merge pinned to
the reviewed commit; anything touching CI, agent instructions, credentials or the sandbox's own
configuration is left to a human.

### `root-init.sh` — root stage (in the container)

Sourced by `entrypoint.sh` as root, in POSIX `sh`, for setup that needs root: a trust store, a
daemon, packages, a device's group. Not a boundary: the agent can be root in its container, so
whatever enters the container — netbird's setup key, say — is the agent's. Anything derived from a
long-lived credential is minted on the host instead (`register_credential`). Anything you `export`
survives the `setpriv` handoff to `node`.

Context: `$PLUGIN_NAME`, `$PLUGIN_DIR` (`/opt/plugins/<name>`), `$ENABLED_PLUGINS`, `$RUN_ID`,
`$RESUME`, plus every `-e` var the host stage passed in.

```sh
# shellcheck shell=sh
netbird up --setup-key "$NB_SETUP_KEY" ...
unset NB_SETUP_KEY   # out of the agent's environment, so it is not printed by mistake
```

### `agent-init.sh` — agent stage (`node`)

Sourced by `agent-setup.sh` as the agent user, in POSIX `sh`, after the agent seeded its own
config. Use it for authentication with short-lived tokens, the helpers the agent's tools talk to
(upstream-proxy's forwarder, gcp-auth's metadata server, the ports helper), provisioning
`/workspace`, and briefing the agent.

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

Merged by `src/services/settings/merge-settings.py` into the selected agent's `managedSettings` path at boot
(`/etc/claude-code/managed-settings.json` for `claude`), in priority order, starting from
`settings-base.json` (an empty `{}`). Merge rules:

- objects merge key by key,
- lists **concatenate**, so several plugins can each add an entry to the same `hooks` array,
- on scalar conflicts the later (higher-priority-number) fragment wins.

The result is written by root, outside `/workspace`, mode `0444`, so the agent does not relax
its own policy by accident; a guardrail, like every hook in it. Fragments are written in the schema of one agent, so a plugin contributing one
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

### `bin/`

| Directory | Mode | Owner-visible to | Use for |
|-----------|------|------------------|---------|
| `bin/` | 555 | everyone, incl. `node` | hook scripts and helpers Claude or the agent stage invokes |

Everything else under the plugin directory is 444 with 555 directories.

## Environment variables

Every variable must have an entry in `.env.example`, which doubles as the allowlist of
sandbox-owned names. Configuration is per-project: it lives in the project's
file (these variables in its `env` block), never in a `.env` and never in the sandbox's own directory. Only `AGENT` belongs to the core; the rest are owned by an agent or a plugin and
only required while that agent or plugin is in use.

| Variable | Owner | Purpose |
|----------|-------|---------|
| `AGENT` | core | Which agent runs: a directory name under `agents/` (default `claude`) |
| `PROJECT_CONFIG_FILE` | core | The project's file; `--project <name>` sets it to `~/.config/claude-sandbox/projects/<name>.json` (optional) |
| `SANDBOX_AUTH_FILE` | core | Your named authentications (default `~/.config/claude-sandbox/auth.json`), see [Authentications](#authentications--configclaude-sandboxauthjson); shell only |
| `SANDBOX_WEB_BIND` / `SANDBOX_WEB_NAME` | core | Set by the web UI for every `run.sh` it starts: the address it listens on, and the host name its `--bind` gave for it (plugins that publish what a session serves default to it) |
| `PORTS` | ports | Space-separated ports a sandbox opens: published on the host, and shown on the dashboard, while something in it listens on them (default: none) |
| `PORTS_BIND` | ports | Address the central port proxy publishes the sandboxes' ports on (default: `SANDBOX_WEB_BIND`, else `127.0.0.1`; `0.0.0.0` for your whole network) |
| `CLAUDE_AUTH` | agents/claude | Name of the `claude-token` authentication Claude Code runs with. Required unless a plugin sets `AGENT_AUTH_PROVIDED=1`, as `claude-home` does |
| `CLAUDE_EFFORT` | agents/claude | Reasoning effort Claude Code runs at: `low`, `medium` (the sandbox default), `high`, `xhigh`, `max` |
| `CLAUDE_MODEL` | agents/claude | Model Claude Code starts on, an alias (`opus`) or a full id (default: Claude Code's own default) |
| `COPILOT_AUTH` | agents/copilot | Name of the `copilot-token` authentication Copilot runs with. Required unless a plugin sets `AGENT_AUTH_PROVIDED=1`, as `copilot-home` does |
| `ENABLE_GITHUB_AUTH` / `ENABLE_GIT_WORKSPACE` / `ENABLE_CWD_WORKSPACE` / `ENABLE_AGENT_WORKSPACE` / `ENABLE_BRANCH_GUARD` / `ENABLE_CLAUDE_HOME` / `ENABLE_COPILOT_HOME` / `ENABLE_DOCKER_CLI` / `ENABLE_CA_CERTS` / `ENABLE_DEV_SERVER` / `ENABLE_PORTS` / `ENABLE_UPSTREAM_PROXY` / `ENABLE_PROJECT_DEPS` / `ENABLE_NETBIRD` / `ENABLE_GCP_AUTH` / `ENABLE_SSH_CREDENTIALS` / `ENABLE_PR_REVIEW` | core | plugin switches (default on, except `ca-certs`, `cwd-workspace`, `gcp-auth`, `netbird`, `pr-review` and `ssh-credentials`) |
| `GH_AUTH` | github-auth | Name of the `github-app` authentication the sandbox authenticates as |
| `BASE_BRANCH` | git-workspace | Branch to cut from (default: the repo's own default branch, via `origin/HEAD`) |
| `HOST_WORKSPACE_DIR` | cwd-workspace | Host dir mounted at `/workspace` (default: `run.sh`'s cwd) |
| `BRANCH_PREFIX` | git-workspace | Leading segment of the per-run branch name; `.plugins["git-workspace"].branchPrefix` in the project's file wins over it, and with neither it defaults to the agent manifest's `branchPrefix`, else the agent's directory name |
| `AGENT_WORKSPACE_DIR` | agent-workspace | Host dir holding the per-run mirrors of `/workspace`, created if missing (default: `$HOME/.agent-workspaces`; each run uses `<dir>/<project>-<date>-<RUN_ID>`) |
| `AGENT_WORKSPACE_CLEANUP` | agent-workspace | Delete the run's mirror directory when the container exits; 0 keeps it for inspection, at one leftover directory per run (default: 1) |
| `CA_CERTS_DIR` | ca-certs | Host dir holding extra root certificates, PEM or DER (default `/usr/local/share/ca-certificates`) |
| `CLAUDE_HOME_DIR` | claude-home | Host dir mounted as the agent's `~/.claude` (default `$HOME/.claude`) |
| `COPILOT_HOME_DIR` | copilot-home | Host dir copied as the agent's `~/.copilot` for each run (default `$HOME/.copilot`) |

Volume mounts are contributed by plugins via `pass_mount`; the core `docker run` has none. The agent's
user, `node`, takes the uid of whoever runs `run.sh` (`HOST_UID`, set by the boot in
`src/boot/entrypoint.sh`), so what is mounted from the host is the agent's own and what the agent
writes in `/workspace` is yours: a web server running as a service user, not uid 1000, still hands
its sessions a `~/.claude` they can read, and can delete a run's mirror afterwards.

## Security model

The boundary is between the container and your machine; there is none inside the container.
Everything in it is the agent's: `node` is in the `docker` group, so the agent is root there
whenever it wants, and whatever enters the container — a token, a setup key, a file — it has.
What runs in the container is a **guardrail**, there to keep a well-meaning agent on track, never to
hold against one that is not:

- `branch-guard` blocks `git checkout/switch/branch/worktree` and pushes of other branches; the
  managed settings, `/opt/plugins` and `/opt/agents` are root-owned and read-only. What actually
  keeps a branch safe is the forge's branch protection, and what the token may do.
- `DISABLE_AUTOUPDATER=1` / `COPILOT_AUTO_UPDATE=false` — the agent version is pinned at image
  build time.

Nothing the container does may reach your machine, so every part on the host treats what comes out
of it as hostile:

- Long-lived keys stay on the host: the GitHub App private key, service-account credentials and
  the proxies' keys never enter the container; it gets short-lived tokens in `/run/credentials`,
  mounted read-only.
- Nothing on the host runs what the container wrote: the changes a run made are listed by git
  inside its container (`docker exec`), never in its mirror here, whose `.git/config` is the
  agent's; `claude-home` mounts a copy of `~/.claude` per run and takes back only a validated login.
- What the host connects to, it checks each time: the port proxy publishes only the run's `PORTS`
  and opens each socket without following symlinks; upstream-proxy's sockets are mounted
  read-only, so no sandbox can put itself between another one and the proxy.
- Plugins that hand the container a part of your machine by design — `cwd-workspace` (your
  checkout), `data-mounts` (what you list), `libvirt` (your VMs) — do nothing until you switch them on or
  list what to mount, and give the agent exactly that: switch one on only for what you would let the agent run on your machine.

## Repository layout

The core is grouped by role under `src/`; each folder has one reason to change.

| Path | Purpose |
|------|---------|
| [install.sh](install.sh) | sets a checkout up: host requirements, the uv environment, the web UI's build, the `claude-sandbox` commands |
| [run.sh](run.sh) | host entry point; runs [src/orchestrator](src/orchestrator) in the uv environment |
| [pyproject.toml](pyproject.toml), [uv.lock](uv.lock) | the uv project: Python version, and the test tools as its `dev` group |
| [Dockerfile](Dockerfile) | image: base tools, agent install stage, plugin install stage, permissions |
| [src/orchestrator/](src/orchestrator) | **decides what a run is and starts it** (Python): the command line, build and `docker run` (`main.py`), project config and settings (`config.py`), named authentications (`auth.py`), agent (`agents.py`) and plugin (`plugins.py`) resolution, the plugins' stages (`stage.py`), the sandbox's own settings (`kernel.json`) |
| [src/contract/host/](src/contract/host) | **what a plugin's or agent's `host.sh` / `web.sh` is sourced with** (bash): `stage.sh` (the shell that sources them), `plugins.sh` (`pass_*`, `on_exit`, `web_*`), `agents.sh`, `project-config.sh` (`plugin_config`) |
| [src/contract/container/](src/contract/container) | the same contract in the image: `plugins.sh` (stage runner, fragment/secret listing), `agents.sh` (manifest lookup, stage runner) |
| [src/boot/](src/boot) | **from started container to running agent**: `entrypoint.sh` (root stage, privilege handoff), `agent-setup.sh` (agent stage, launch) |
| [src/services/credentials/](src/services/credentials) | `register_credential`: minting on the host, refreshing, the `/run/credentials` mount |
| [src/services/settings/](src/services/settings) | the agent's managed policy: `merge-settings.py` deep-merges plugin fragments into `settings-base.json` |
| [src/services/chat/](src/services/chat) | `chat-bridge.mjs`: the chat events the agents' `chat.mjs` speak and the web UI draws |
| [src/server/](src/server) | **the web UI's server** over `run.sh`: `server.py` (sessions, PRs and issues, a tunnel to `code serve-web`, the pages), `holder.py` (what keeps a session running through a restart of the server), `serve.sh` (starts it in the uv environment), `serve-oauth.sh` (the same behind Google sign-in) |
| [web/](web) | the web UI's pages — a React app (Vite, TypeScript): the dashboard, a session's chat, a terminal (`src/pages`), their components by feature (`src/components`), `src/hooks`, `src/api`, `src/lib`, `src/styles` |
| [agents/](agents) | the agents themselves |
| [plugins/](plugins) | the plugins themselves |
| [tests/](tests) | pytest suite (`uv run pytest`); `tests/e2e` boots the built image |

## Dependencies

The project is a [uv](https://docs.astral.sh/uv/) project: `uv sync` creates `.venv` from
`uv.lock`, and `run.sh`, `src/server/serve.sh` and the plugins' host scripts (their `python3`) run in
it. Add a library with `uv add <package>` where it saves code that would otherwise be maintained
here — `requests` for the GitHub API (`plugins/github-auth/host/github.py`), say. Scripts that run
inside the container use the image's system Python, so they stay standard library.
