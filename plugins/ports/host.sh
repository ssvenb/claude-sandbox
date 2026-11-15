# shellcheck shell=bash
# Host stage: joins the central port proxy for this run when PORTS lists any (host/lease.py), and
# hands the container the directory its sockets go in. The stage's shell ($$) stands for the run:
# it lives until the container is gone, and the proxy forgets a run whose shell died.

PORTS_LEASE="$PLUGIN_DIR/host/lease.py"   # $PLUGIN_DIR is gone by the time the exit hook runs
ports_leave() { "$PORTS_LEASE" leave "$RUN_ID" $$; }
on_exit ports_leave
PORTS_ARGS=$("$PORTS_LEASE" join "$RUN_ID" $$)
[ -z "$PORTS_ARGS" ] || { mapfile -t PORTS_ARGS <<<"$PORTS_ARGS"; pass_arg "${PORTS_ARGS[@]}"; }
unset PORTS_ARGS
