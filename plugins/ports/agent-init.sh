# shellcheck shell=sh
# Agent stage: offer each configured port the agent's servers listen on to the host's central
# proxy, as unix sockets in the directory host.sh mounted (bin/publish-ports.py). The directory is
# the agent's, like everything in the container: the host proxy follows nothing planted there
# (host/portd.py), and publishes only the ports this run's PORTS lists.
if [ -d /run/ports/sockets ]; then
  _ports=""
  for _port in ${PORTS:-}; do _ports="$_ports --port $_port"; done
  mkdir -p "$HOME/.cache"
  # shellcheck disable=SC2086  # one --port PORT pair per port
  [ -z "$_ports" ] || "$PLUGIN_DIR/bin/publish-ports.py" --log "$HOME/.cache/ports.log" $_ports /run/ports/sockets
  unset _ports _port
fi

# What becomes of the ports it serves on. The agent would otherwise assume a shared network, or
# spend a turn wondering how the user reaches its server.
if [ -d /run/ports/sockets ]; then
  {
    printf '\n## Ports\n\n'
    printf 'This container has a network of its own. The project publishes these TCP ports: %s. ' \
      "$(printf '%s' "${PORTS:-}" | sed 's/ /, /g')"
    printf 'Whatever a process of yours listens on one of them (on any address, 127.0.0.1 '
    printf 'included) reaches the user within a second or two, through a proxy on their machine, '
    printf 'and shows as a button on your session in their dashboard; any other port stays inside '
    printf 'this container, so serve what the user should see on one of those. There it gets the '
    printf 'same port number while that is free, otherwise another one, since other sessions may '
    printf 'serve on the same port: do not assume the number the user sees. Services the host '
    printf 'machine offers on a non-loopback address are at host.docker.internal; its localhost is '
    printf 'not reachable from here.\n'
  } >>"$AGENT_PROMPT_FILE"
fi
