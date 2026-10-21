# shellcheck shell=bash
# Short-lived credentials, minted on the HOST and refreshed for the life of the run. Sourced by
# run.sh (bash, on YOUR machine).
#
# Whatever a credential is derived from — an App private key, your own cloud login — stays here:
# the container only ever sees the minted result, as a file under /run/credentials (a read-only
# mount of a directory only your user can reach on the host). A plugin's host.sh registers one:
#
#   github_auth_mint() { "$GITHUB_AUTH_DIR/host/mint-gh-token.py"; }
#   register_credential github-token 2400 github_auth_mint
#
# The function prints the credential on stdout. The core first calls it after every plugin's host
# stage — so it may use values a later plugin sets, like git-workspace's REPO_URL — and fails the
# run if it does, then again every INTERVAL seconds in the background, replacing the file
# atomically. The deadline is wall-clock, checked every minute: sleep's clock stops while the host
# is suspended, so a single long sleep would outlive the credential after a suspend. A failed
# refresh is logged and retried a minute later, while the previous credential stays in place.
#
# In the container, read /run/credentials/<name> each time it is needed, or watch it for changes;
# a copy taken at boot goes stale after INTERVAL.

CREDENTIALS=()   # "<name> <interval> <function>"

# register_credential <name> <interval-seconds> <function>
register_credential() {
  local name=$1 interval=$2 func=$3
  [[ $name =~ ^[a-z0-9][a-z0-9.-]*$ ]] \
    || die "Plugin '${PLUGIN_NAME:-?}': credential name '$name' must be lowercase letters, digits, '.' and '-'."
  [[ $interval =~ ^[0-9]+$ ]] && [ "$interval" -ge 60 ] \
    || die "Plugin '${PLUGIN_NAME:-?}': credential '$name' needs a refresh interval of at least 60 seconds."
  declare -F "$func" >/dev/null \
    || die "Plugin '${PLUGIN_NAME:-?}': credential '$name' names '$func', which is not a shell function."
  CREDENTIALS+=("$name $interval $func")
}

# Mint one credential into place. A failure, or empty output, leaves the previous file untouched.
credential_mint() {
  local name=$1 func=$2
  local tmp="$CREDENTIALS_DIR/.$name.tmp"
  if ( umask 022; "$func" >"$tmp" ) && [ -s "$tmp" ]; then
    mv -f "$tmp" "$CREDENTIALS_DIR/$name"
  else
    rm -f "$tmp"
    return 1
  fi
}

# Stop writing before the directory goes.
credentials_stop() {
  [ -z "${CREDENTIALS_PID:-}" ] || kill "$CREDENTIALS_PID" 2>/dev/null || true
  rm -rf "$CREDENTIALS_ROOT"
}

# Mint everything registered, start the refresher and mount the result. Called once by run.sh,
# after every host stage.
credentials_start() {
  local entry name interval func
  [ ${#CREDENTIALS[@]} -gt 0 ] || return 0

  # mktemp -d is 0700, so other users on this machine cannot reach the files inside.
  CREDENTIALS_ROOT=$(mktemp -d -t sandbox-credentials-XXXXXX)
  CREDENTIALS_DIR="$CREDENTIALS_ROOT/credentials"
  mkdir -m 755 "$CREDENTIALS_DIR"
  # Not run.sh's terminal: the agent's TUI shares it, and a line written there would scribble
  # over the screen.
  CREDENTIALS_LOG="$CREDENTIALS_ROOT/refresh.log"
  on_exit credentials_stop

  for entry in "${CREDENTIALS[@]}"; do
    read -r name interval func <<<"$entry"
    credential_mint "$name" "$func" 2>"$CREDENTIALS_LOG" \
      || die "Could not mint credential '$name':"$'\n'"$(cat "$CREDENTIALS_LOG")"
  done

  (
    declare -A next=()
    now=$(date +%s)
    for entry in "${CREDENTIALS[@]}"; do
      read -r name interval func <<<"$entry"
      next[$name]=$(( now + interval ))
    done
    while sleep 60; do
      # $$ is run.sh: stop with it, even if it was killed before its exit hooks could run.
      kill -0 $$ 2>/dev/null || exit 0
      now=$(date +%s)
      for entry in "${CREDENTIALS[@]}"; do
        read -r name interval func <<<"$entry"
        [ "$now" -ge "${next[$name]}" ] || continue
        if credential_mint "$name" "$func"; then
          next[$name]=$(( now + interval ))
          echo "$(date '+%F %T') refreshed $name"
        else
          echo "$(date '+%F %T') could not refresh $name; retrying in a minute"
        fi
      done
    done
  ) </dev/null >>"$CREDENTIALS_LOG" 2>&1 &
  CREDENTIALS_PID=$!

  pass_mount "$CREDENTIALS_DIR" /run/credentials ro
  echo "🔑 Credentials: $(printf '%s\n' "${CREDENTIALS[@]}" | cut -d' ' -f1 | paste -sd' ' -) (refresh log: $CREDENTIALS_LOG)"
}
