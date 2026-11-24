# shellcheck shell=bash
# Host stage: the project's server command, from its config —
#
#   { "plugins": { "dev-server": { "command": "pnpm dev --host 0.0.0.0 --port 3000", "port": 3000,
#                                  "demoSetup": ["./scripts/seed-demo-data"] } } }
#
# The command runs in the sandbox at every boot, for the agent's own checks (agent-init.sh); nothing
# there is published. With a port, it runs a second time for you: once the run's container is up, a
# sibling one from the same image serves the agent's checkout (agent-workspace's mirror), runs
# demoSetup first, restarts the command on every change (bin/demo-server), and its port is published
# as a button on the run's session. The agent's code runs in there, never on this machine. It gets
# what the sibling plugins hand the sandbox, and with .agentHome true the agent's home (the run's
# copy of your ~/.claude, when the sandbox has it too), never the App key or the host's Docker socket.
# No command → the plugin does nothing, which is why it can stay on by default.

DEV_SERVER_COMMAND=$(plugin_config '.command' '')
[ -n "$DEV_SERVER_COMMAND" ] || return 0
pass_value DEV_SERVER_COMMAND "$DEV_SERVER_COMMAND"
echo "🚀 dev-server: starting \`$DEV_SERVER_COMMAND\` at boot"

# No port → no demo container: the server runs in the sandbox alone.
DEMO_SERVER_PORT=$(plugin_config '.port' '')
[ -n "$DEMO_SERVER_PORT" ] || return 0
[[ $DEMO_SERVER_PORT =~ ^[0-9]+$ ]] || die "dev-server: .plugins[\"dev-server\"].port must be a port number (got: '$DEMO_SERVER_PORT')."
DEMO_SERVER_SETUP=$(plugin_config_json '.demoSetup' '[]')
printf '%s' "$DEMO_SERVER_SETUP" | jq -e 'type == "array" and all(type == "string")' >/dev/null 2>&1 \
  || die "dev-server: .plugins[\"dev-server\"].demoSetup must be an array of strings."

# What the sibling plugins hand the sandbox (plugin_siblings: a proxy's sockets, certificates,
# Sysbox and its Docker daemon): the demo container takes their args and runs their container stages
# (bin/demo-server). And, with .agentHome true, the agent's home (AGENT_HOME_ARGS: Claude's copy of
# your ~/.claude).
DEMO_SERVER_PLUGINS=$(plugin_siblings | xargs)
# shellcheck disable=SC2086  # one argument per plugin name
plugin_docker_args $DEMO_SERVER_PLUGINS
DEMO_SERVER_ARGS=(${PLUGIN_DOCKER_ARGS[@]+"${PLUGIN_DOCKER_ARGS[@]}"} -e "DEMO_SERVER_PLUGINS=$DEMO_SERVER_PLUGINS")
case $(plugin_config '.agentHome' 'false') in
  true) DEMO_SERVER_ARGS+=(${AGENT_HOME_ARGS[@]+"${AGENT_HOME_ARGS[@]}"}) ;;
  false) ;;
  *) die "dev-server: .plugins[\"dev-server\"].agentHome must be true or false." ;;
esac

# agent-workspace (priority 15) made the mirror already.
DEMO_SERVER_MIRROR=$(ls -d "${AGENT_WORKSPACE_DIR:-$HOME/.agent-workspaces}"/*-"$RUN_ID" 2>/dev/null | head -n 1) || true
[ -n "$DEMO_SERVER_MIRROR" ] || die "dev-server: a port needs agent-workspace's mirror of /workspace, which the demo container serves."

# Where the web UI listens (src/server/server.py exports it for every run it starts), so the link
# works from wherever the page was opened: {host} is the name the page was opened by.
DEMO_SERVER_BIND=${SANDBOX_WEB_BIND:-127.0.0.1}
case $DEMO_SERVER_BIND in
  0.0.0.0|127.0.0.1) DEMO_SERVER_HOST='{host}' ;;
  *) DEMO_SERVER_HOST=${SANDBOX_WEB_NAME:-$DEMO_SERVER_BIND} ;;
esac
DEMO_SERVER_STATE=$HOME/.local/state/claude-sandbox/dev-server
mkdir -p "$DEMO_SERVER_STATE"

# demo_server_items <jq filter>: the run's link on the web UI's session row (web.sh), one file for
# every run, rewritten under a lock.
demo_server_items() {
  (
    flock 9
    items=$({ cat "$DEMO_SERVER_STATE/items.json" 2>/dev/null || echo '[]'; } \
      | jq -c "map(select(.run_id != \"$RUN_ID\")) | $1")
    printf '%s\n' "$items" >"$DEMO_SERVER_STATE/items.json"
  ) 9>"$DEMO_SERVER_STATE/items.lock"
}

# In the background: the image is built and the container started only after the host stages.
(
  name=sandbox-demo-$RUN_ID
  until image=$(docker inspect -f '{{.Image}}' "sandbox-$RUN_ID" 2>/dev/null); do sleep 2; done
  docker run -d --rm --name "$name" ${DEMO_SERVER_ARGS[@]+"${DEMO_SERVER_ARGS[@]}"} \
    -v "$DEMO_SERVER_MIRROR:/workspace" -p "$DEMO_SERVER_BIND::$DEMO_SERVER_PORT" \
    -e "HOST_UID=$(id -u)" -e "DEMO_SERVER_COMMAND=$DEV_SERVER_COMMAND" -e "DEMO_SERVER_SETUP=$DEMO_SERVER_SETUP" \
    --entrypoint /opt/plugins/dev-server/bin/demo-server "$image" >/dev/null || exit 1
  published=$(docker port "$name" "$DEMO_SERVER_PORT/tcp" | head -n 1)
  url="http://$DEMO_SERVER_HOST:${published##*:}/"
  demo_server_items ". + [{run_id: \"$RUN_ID\", ref: \"demo\", url: \"$url\", title: \"The run's checkout, served by $name (docker logs $name)\"}]"
  echo "🧪 dev-server: $url"
) >>"$DEMO_SERVER_STATE/$RUN_ID.log" 2>&1 &
DEMO_SERVER_PID=$!
echo "🧪 dev-server: starts with the container (log: $DEMO_SERVER_STATE/$RUN_ID.log)"

# demo_server_items and DEMO_SERVER_STATE stay defined for the hook.
on_exit "kill $DEMO_SERVER_PID 2>/dev/null || true; docker rm -f sandbox-demo-$RUN_ID >/dev/null 2>&1 || true; rm -f '$DEMO_SERVER_STATE/$RUN_ID.log'; demo_server_items ."
unset DEMO_SERVER_PORT DEMO_SERVER_SETUP DEMO_SERVER_PLUGINS DEMO_SERVER_ARGS DEMO_SERVER_MIRROR DEMO_SERVER_BIND DEMO_SERVER_HOST DEMO_SERVER_PID
