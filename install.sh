#!/usr/bin/env bash
# Sets this checkout up to run sandboxes and their web UI: checks what the host needs, creates the
# Python environment (uv), builds the web UI (npm) and puts two commands on your PATH.
#
#   ./install.sh [--yes] [--dev] [--no-web] [--no-launchers] [--project DIR]...
#
#   --yes           install what is missing (uv; jq, git, curl through the system's package
#                   manager) without asking
#   --dev           also what the tests need: pytest, Playwright and its Chromium
#   --no-web        skip the web UI (no Node needed): run.sh alone
#   --no-launchers  do not link `claude-sandbox` and `claude-sandbox-web` into ~/.local/bin
#   --project DIR   list DIR on the web UI's dashboard (~/.config/claude-sandbox/projects); repeatable
#
# Safe to run again: it only adds what is missing, and rebuilds the web UI.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
YES=0 DEV=0 WEB=1 LAUNCHERS=1 PROJECTS=()
NODE_MIN=20.19  # what the web UI's build (Vite) needs: web/ui/package.json's engines

usage() { sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
while [ $# -gt 0 ]; do
  case "$1" in
    -y|--yes) YES=1 ;;
    --dev) DEV=1 ;;
    --no-web) WEB=0 ;;
    --no-launchers) LAUNCHERS=0 ;;
    --project) [ $# -ge 2 ] || { echo "--project needs a directory." >&2; usage 1 >&2; }
      PROJECTS+=("$2"); shift ;;
    -h|--help) usage ;;
    *) echo "Unknown argument: $1" >&2; usage 1 >&2 ;;
  esac
  shift
done

say()  { printf '%s\n' "$*"; }
step() { printf '\n▸ %s\n' "$*"; }
ok()   { printf '  ✓ %s\n' "$*"; }
warn() { printf '  ⚠️  %s\n' "$*" >&2; }
die()  { printf '❌ %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# confirm <question>: yes with --yes; asks on a terminal; no otherwise.
confirm() {
  [ "$YES" = 1 ] && return 0
  [ -t 0 ] || return 1
  local answer
  read -r -p "  $1 [y/N] " answer
  case "$answer" in y|Y|yes|Yes) return 0 ;; *) return 1 ;; esac
}

# The system's package manager, as the command that installs packages; empty when unknown.
pkg_install=""
sudo=""; [ "$(id -u)" = 0 ] || sudo="sudo"
if have apt-get; then pkg_install="$sudo apt-get install -y"
elif have dnf; then pkg_install="$sudo dnf install -y"
elif have pacman; then pkg_install="$sudo pacman -S --noconfirm"
elif have zypper; then pkg_install="$sudo zypper install -y"
elif have brew; then pkg_install="brew install"
fi

# need <command> <package> <why>: the command, or its package installed after a yes; else a failure
# that says what to do.
MISSING=()
need() {
  local cmd=$1 pkg=$2 why=$3
  if have "$cmd"; then ok "$cmd"; return 0; fi
  if [ -n "$pkg_install" ] && confirm "$cmd is missing ($why). Install it with: $pkg_install $pkg ?"; then
    $pkg_install "$pkg" && have "$cmd" && { ok "$cmd (installed)"; return 0; }
  fi
  warn "$cmd is missing: $why.${pkg_install:+ Install it with: $pkg_install $pkg}"
  MISSING+=("$cmd")
}

step "Checking what the host needs"
[ "$(uname -s)" = Linux ] || warn "Only Linux hosts are tested; on $(uname -s) some plugins' host stages may not work."
need git git "git-workspace reads the repo you launch from"
need jq jq "the plugins' host stages read their settings with it"
have uv || need curl curl "installing uv"
if have docker; then ok docker
else  # its package differs per distribution, and Docker's own repository is usually the better source
  warn "docker is missing: sandboxes are containers. Install Docker Engine: https://docs.docker.com/engine/install/"
  MISSING+=(docker)
fi
if have docker && ! docker info >/dev/null 2>&1; then
  warn "docker is installed but its daemon does not answer: start it, and add yourself to the docker group if needed (sudo usermod -aG docker \$USER, then log in again)."
fi
have flock || warn "flock (util-linux) is missing: the upstream-proxy plugin needs it."
[ ${#MISSING[@]} -eq 0 ] || die "Install what is missing (${MISSING[*]}) and run ./install.sh again, or pass --yes to let it."

step "Python environment (uv)"
if ! have uv; then
  # Its installer puts uv in ~/.local/bin, which may not be on this shell's PATH yet.
  export PATH="$HOME/.local/bin:$PATH"
fi
if ! have uv; then
  confirm "uv is missing. Install it with its official installer (https://astral.sh/uv/install.sh)?" \
    || die "uv is required: see https://docs.astral.sh/uv/getting-started/installation/"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  have uv || die "uv was installed but is not on the PATH: open a new shell and run ./install.sh again."
fi
ok "$(uv --version)"
if [ "$DEV" = 1 ]; then
  uv sync --project "$here" --frozen
  uv run --project "$here" --no-sync playwright install chromium
else
  # --inexact: a second run without --dev leaves the test tools of an earlier --dev in place.
  uv sync --project "$here" --frozen --no-dev --inexact
fi
ok "environment: $here/.venv"

if [ "$WEB" = 1 ]; then
  step "Web UI (React, built with npm)"
  if ! have node && [ -n "${SHELL:-}" ]; then
    # Run from a service or cron, PATH lacks what the user's shell rc adds (nvm, fnm, volta): take that PATH.
    rc_path=$("$SHELL" -ic 'printf "\n%s" "$PATH"' </dev/null 2>/dev/null | tail -n1) && [ -n "$rc_path" ] && export PATH="$rc_path"
  fi
  node_ok=0
  have node && node_ok=$(node -p "const [a, b] = process.versions.node.split('.').map(Number), [x, y] = '$NODE_MIN'.split('.').map(Number); a > x || (a === x && b >= y) ? 1 : 0" 2>/dev/null || echo 0)
  if ! have npm || [ "$node_ok" != 1 ]; then
    if have node; then found="node $(node --version) is too old"; else found="node is missing"; fi
    # Distribution packages are often older than that, so say where a current one comes from.
    die "$found: building the web UI needs Node $NODE_MIN or later, with npm.
   Install it (https://nodejs.org/en/download, or your package manager's nodejs + npm if recent enough)
   and run ./install.sh again — or pass --no-web to set up run.sh alone."
  fi
  ok "node $(node --version), npm $(npm --version)"
  (cd "$here/web/ui" && npm ci --no-audit --no-fund && npm run build)
  ok "built: $here/web/ui/dist"

  step "Projects on the dashboard"
  listing="${XDG_CONFIG_HOME:-$HOME/.config}/claude-sandbox/projects"
  mkdir -p "$(dirname "$listing")"
  [ -f "$listing" ] || printf '# One project directory per line; a line may be a glob (~/code/*/.git lists the git checkouts).\n' >"$listing"
  for project in ${PROJECTS[@]+"${PROJECTS[@]}"}; do
    [ -d "$project" ] || die "--project $project: no such directory."
    project=$(cd "$project" && pwd)
    grep -qxF "$project" "$listing" || printf '%s\n' "$project" >>"$listing"
  done
  ok "$listing ($(grep -cvE '^\s*(#|$)' "$listing" || true) listed)"
fi

if [ "$LAUNCHERS" = 1 ]; then
  step "Commands"
  bin="$HOME/.local/bin"
  mkdir -p "$bin"
  ln -sfn "$here/run.sh" "$bin/claude-sandbox"
  ok "claude-sandbox      → $here/run.sh"
  if [ "$WEB" = 1 ]; then
    ln -sfn "$here/src/server/serve.sh" "$bin/claude-sandbox-web"
    ok "claude-sandbox-web  → $here/src/server/serve.sh"
  fi
  case ":$PATH:" in *":$bin:"*) ;; *) warn "$bin is not on your PATH: add it (export PATH=\"\$HOME/.local/bin:\$PATH\") to use them." ;; esac
fi

if [ "$WEB" = 1 ] && have systemctl; then
  step "Service (systemd)"
  service=claude-sandbox-web.service
  units="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  start="ExecStart=$here/src/server/serve.sh"
  if [ -f "$units/$service" ] && ! grep -qxF "$start" "$units/$service"; then
    # One this script wrote before the server moved out of web/: pointed at where it is now.
    sed -i "s|^ExecStart=.*|$start|" "$units/$service"
    systemctl --user daemon-reload
    ok "$service (now runs $here/src/server/serve.sh)"
  elif systemctl cat "$service" >/dev/null 2>&1 || systemctl --user cat "$service" >/dev/null 2>&1; then
    ok "$service (already registered)"
  elif systemctl --user show-environment >/dev/null 2>&1; then
    mkdir -p "$units"
    # PATH as this shell has it: the server runs docker, uv, git and jq.
    cat >"$units/$service" <<UNIT
[Unit]
Description=claude-sandbox web UI
After=network-online.target

[Service]
$start
Environment="PATH=$PATH"
Restart=on-failure

[Install]
WantedBy=default.target
UNIT
    systemctl --user daemon-reload
    systemctl --user enable --now "$service"
    ok "$service (user service; loginctl enable-linger keeps it running while you are logged out)"
  else
    warn "no systemd user session: $service not registered."
  fi
fi

step "Done"
say "  In a repo you want an agent to work on:"
say "    cp $here/.env.example .env      # pick AGENT, fill in its token and any plugin settings"
say "    claude-sandbox                  # or $here/run.sh"
if [ "$WEB" = 1 ]; then
  say "  The web UI, for every project listed in ${listing/#$HOME/\~}:"
  say "    claude-sandbox-web              # http://127.0.0.1:8787"
fi
