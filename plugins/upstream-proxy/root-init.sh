# shellcheck shell=sh
# Root stage. Bridge each bind-mounted unix socket to a loopback TCP port so ordinary HTTP clients
# can reach it. No secret here — the credential lives in the host proxy on the far side — but socat
# runs as root so `node` cannot replace a forwarder and point an endpoint somewhere else.

for entry in ${UPSTREAM_PROXY_PORTS:-}; do
  name=${entry%%:*}
  port=${entry##*:}
  sock="/run/upstream-proxy/$name.sock"
  if [ ! -S "$sock" ]; then
    echo "⚠️  upstream-proxy: $sock is missing, skipping $name" >&2
    continue
  fi
  socat "TCP4-LISTEN:$port,bind=127.0.0.1,fork,reuseaddr" "UNIX-CONNECT:$sock" &
  echo "🔌 upstream-proxy: 127.0.0.1:$port → $name"
done
