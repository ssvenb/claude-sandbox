#!/bin/bash
# The plugins' and the agent's host stages: one bash, started by the Python side of run.sh
# (src/orchestrator/stage.py) once it has resolved the project's settings, the agent and the plugins. It
# sources each enabled plugin's host.sh or web.sh with the helpers of src/contract/host/*.sh, exactly as
# run.sh used to source them into itself. What they produced goes to files in
# $SANDBOX_STAGE_REPORT (NUL-separated lists: docker, build, env; or web.json), and then one line,
# "done", on $SANDBOX_STAGE_REPORT_FD.
#
#   stage.sh host                           plugins' host.sh, the agent's host.sh, credentials;
#                                                then waits on stdin, and runs the exit hooks at EOF
#   stage.sh web                            plugins' web.sh: the page's WEB_JSON
#   stage.sh web-action <plugin> <action> <arg>
#
# Its environment carries what src/orchestrator resolved: HOST_CWD, RUN_ID, RUN_DATE, RESUME, AGENT,
# AGENT_DIR, ENABLED_PLUGINS, PLUGIN_ROOT, PROJECT_CONFIG_FILE, PROJECT_CONFIG_JSON,
# PROJECT_ENV_FILE, and the project's settings already applied.
set -euo pipefail
cd "$(dirname "$0")/../../.."

# shellcheck source=src/contract/host/plugins.sh
. src/contract/host/plugins.sh
# shellcheck source=src/services/credentials/credentials.sh
. src/services/credentials/credentials.sh
# shellcheck source=src/contract/host/agents.sh
. src/contract/host/agents.sh
# shellcheck source=src/contract/host/project-config.sh
. src/contract/host/project-config.sh
# shellcheck source=src/contract/host/project-env.sh
. src/contract/host/project-env.sh

REPORT_FD=${SANDBOX_STAGE_REPORT_FD:?stage.sh is started by run.sh}
REPORT=${SANDBOX_STAGE_REPORT:?stage.sh is started by run.sh}
# Context for the stages, not for what they start: run.sh never exported these.
export -n SANDBOX_STAGE_REPORT_FD SANDBOX_STAGE_REPORT PROJECT_CONFIG_JSON AGENT_DIR ENABLED_PLUGINS RESUME
project_env_load

# reported: tells run.sh the report is complete. The pipe is not left to close by itself: what the
# stage started (a proxy, the credentials refresher) holds it open too.
reported() { echo 'done' >&"$REPORT_FD"; exec {REPORT_FD}>&-; }

case "${1:-}" in
  host)
    plugins_host_stage
    agent_host_stage
    # After every host stage, so a credential may depend on what any of them set up.
    credentials_start
    { [ ${#DOCKER_ARGS[@]} -eq 0 ] || printf '%s\0' "${DOCKER_ARGS[@]}"; } >"$REPORT/docker"
    { [ ${#BUILD_ARGS[@]} -eq 0 ] || printf '%s\0' "${BUILD_ARGS[@]}"; } >"$REPORT/build"
    env -0 >"$REPORT/env"
    reported
    # The exit hooks (on_exit) fire once the container is gone: run.sh closes our stdin then, and
    # so does its death, however it comes.
    read -r _ || true
    ;;
  web)
    plugins_web_stage
    printf '%s' "$WEB_JSON" >"$REPORT/web.json"
    reported
    ;;
  web-action)
    [ $# -eq 4 ] || die "web-action needs a plugin, an action and its argument."
    plugins_web_action "$2" "$3" "$4"
    reported
    ;;
  *) die "stage.sh: unknown stage '${1:-}'" ;;
esac
