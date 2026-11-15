# shellcheck shell=sh
# Root stage: offer each configured port the agent's servers listen on to the host's central proxy,
# as unix sockets in the directory host.sh mounted. Its parent goes root-only first, so the agent
# can neither reach the sockets nor plant one of its own for the host to connect to.

if [ -d /run/ports/sockets ]; then
  chmod 700 /run/ports
  _ports=""
  for _port in ${PORTS:-}; do _ports="$_ports --port $_port"; done
  # shellcheck disable=SC2086  # one --port PORT pair per port
  "$PLUGIN_DIR/root/publish-ports.py" --log /var/log/ports.log $_ports /run/ports/sockets
  unset _ports _port
fi
