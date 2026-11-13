# shellcheck shell=bash
# Published ports. Sourced by run.sh (bash, on YOUR machine).
#
# Every sandbox has a network namespace of its own, so two sessions can both serve on :3000.
# Inside, a root helper (src/publish-ports.py, started by entrypoint.sh) offers each port a process
# of the agent's listens on as a unix socket in a directory mounted from here; one central proxy
# on this machine (src/portd.py), shared by every sandbox of every project, gives each a port on
# $PORTS_BIND — the same number while it is free, another free one otherwise. The first run.sh
# starts the proxy; it exits by itself once no run.sh using it is alive.
#
#   ${TMPDIR:-/tmp}/sandbox-ports-<uid>-<bind>/
#     lock            taken to join or leave, and by the proxy before it exits
#     users/<pid>     one per run.sh using the proxy, holding its RUN_ID
#     runs/<RUN_ID>/  the run's sockets, mounted at /run/ports/sockets
#     portd.pid, portd.log, ports.json, items.json (the web UI's session buttons)

SANDBOX_SRC="${SANDBOX_SRC:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

# ports_dir: the central proxy's directory, for this user and $PORTS_BIND.
ports_dir() {
  local bind=${PORTS_BIND:-127.0.0.1}
  printf '%s/sandbox-ports-%s-%s' "${TMPDIR:-/tmp}" "$(id -u)" "${bind//:/_}"
}

# ports_claimed <run_id>: whether a live run.sh other than this one uses that run's directory.
ports_claimed() {
  local f
  for f in "$PORTS_DIR/users"/*; do
    if [ ! -e "$f" ] || [ "${f##*/}" = $$ ] || ! kill -0 "${f##*/}" 2>/dev/null; then continue; fi
    [ "$(cat "$f" 2>/dev/null)" = "$1" ] && return 0
  done
  return 1
}

# Forget the runs whose run.sh died before its exit hook, and their directories.
ports_prune() {
  local f d
  for f in "$PORTS_DIR/users"/*; do
    [ -e "$f" ] || continue
    kill -0 "${f##*/}" 2>/dev/null || rm -f "$f"
  done
  for d in "$PORTS_DIR/runs"/*/; do
    d=${d%/}
    [ -d "$d" ] || continue
    ports_claimed "${d##*/}" || [ "$(cat "$PORTS_DIR/users/$$" 2>/dev/null)" = "${d##*/}" ] || rm -rf "$d"
  done
}

ports_release() {
  local fd
  exec {fd}>"$PORTS_DIR/lock"
  flock "$fd"
  rm -f "$PORTS_DIR/users/$$"
  ports_claimed "$RUN_ID" || rm -rf "${PORTS_DIR:?}/runs/$RUN_ID"
  ports_prune
  # The proxy would exit by itself soon; the last run out need not wait for that.
  if ! compgen -G "$PORTS_DIR/users/*" >/dev/null; then
    kill "$(cat "$PORTS_DIR/portd.pid" 2>/dev/null)" 2>/dev/null || true
    rm -f "$PORTS_DIR/portd.pid" "$PORTS_DIR/ports.json" "$PORTS_DIR/items.json"
  fi
  exec {fd}>&-
}

# ports_start: join (or start) the central proxy for this run, and hand the container its socket
# directory. Its sockets sit under a root-only directory in the container (entrypoint.sh), so the
# agent cannot plant anything there for this machine to connect to.
ports_start() {
  PORTS_BIND=${PORTS_BIND:-127.0.0.1}
  [[ "$PORTS_BIND" =~ ^[0-9A-Fa-f.:]+$ ]] || die "PORTS_BIND must be an IP address (got: $PORTS_BIND)"
  [[ "${PORTS_IGNORE:-}" =~ ^[0-9\ ]*$ ]] || die "PORTS_IGNORE must list port numbers (got: $PORTS_IGNORE)"
  command -v flock >/dev/null || die "flock (util-linux) is required on the host to publish ports."

  PORTS_DIR=$(ports_dir)
  mkdir -p "$PORTS_DIR"
  if [ ! -O "$PORTS_DIR" ] || [ -L "$PORTS_DIR" ]; then die "'$PORTS_DIR' is not yours; remove it and run again."; fi
  mkdir -p "$PORTS_DIR/users" "$PORTS_DIR/runs"
  chmod 700 "$PORTS_DIR" "$PORTS_DIR/users" "$PORTS_DIR/runs"

  local fd pid
  exec {fd}>"$PORTS_DIR/lock"
  flock "$fd"
  printf '%s\n' "$RUN_ID" >"$PORTS_DIR/users/$$"
  ports_prune
  mkdir -p "$PORTS_DIR/runs/$RUN_ID"
  chmod 755 "$PORTS_DIR/runs/$RUN_ID"
  pid=$(cat "$PORTS_DIR/portd.pid" 2>/dev/null || true)
  if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
    "$SANDBOX_SRC/portd.py" --bind "$PORTS_BIND" "$PORTS_DIR" </dev/null >>"$PORTS_DIR/portd.log" 2>&1 {fd}>&- &
    echo $! >"$PORTS_DIR/portd.pid"
  fi
  on_exit ports_release
  flock -u "$fd"
  exec {fd}>&-

  DOCKER_ARGS+=(-v "$PORTS_DIR/runs/$RUN_ID:/run/ports/sockets" -e "PORTS_BIND=$PORTS_BIND"
                --add-host=host.docker.internal:host-gateway)
  [ -z "${PORTS_IGNORE:-}" ] || DOCKER_ARGS+=(-e "PORTS_IGNORE=$PORTS_IGNORE")
  echo "🔌 Ports: whatever the agent serves is published on $PORTS_BIND"
}

# ports_web: the proxy's list of published ports, as session buttons for the web UI.
ports_web() { web_live_items "$(ports_dir)/items.json"; }
