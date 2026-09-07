# shellcheck shell=sh
# Root stage: bring this sandbox's own NetBird client up before the agent starts. Only root can
# create the WireGuard interface and only root holds $NB_SETUP_KEY (entrypoint.sh drops it before
# handing over), so the agent gets mesh connectivity it cannot reconfigure or re-enrol elsewhere.

# Peer name in the dashboard: traceable back to this run. DNS-safe, like RUN_ID.
NB_PEER_NAME="${NB_HOSTNAME:-sandbox-${RUN_ID:-$(openssl rand -hex 3)}}"
export NB_PEER_NAME

netbird service run >/var/log/netbird.log 2>&1 &
for _ in $(seq 1 30); do [ -S /var/run/netbird.sock ] && break; sleep 0.5; done

if netbird up --setup-key "$NB_SETUP_KEY" --hostname "$NB_PEER_NAME" \
     ${NB_MANAGEMENT_URL:+--management-url "$NB_MANAGEMENT_URL"}; then
  echo "✅ NetBird peer enrolled as $NB_PEER_NAME"
  export NB_ENROLLED=1
else
  # Not worth aborting the run over: the agent may have work that never touches the mesh, and peers
  # often only become reachable once a policy is applied elsewhere.
  echo "⚠️  NetBird enrollment failed — see /var/log/netbird.log (continuing without the mesh)"
  export NB_ENROLLED=0
fi
