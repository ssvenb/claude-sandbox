#!/bin/sh
# Build and launch a coding-agent sandbox container. Runs on YOUR machine, where the long-lived
# credentials stay; the container only ever receives what the agent and the enabled plugins hand it.
#
#   run.sh [--resume <RUN_ID> | --run-id <RUN_ID> | --web | --web-action <PLUGIN> <ACTION> <ARG>]
#          [--task TEXT] [--chat]
#
# The work is src/host (Python 3.9+, standard library only); the plugins' and the agent's host.sh
# and web.sh are still bash, sourced by src/lib/host-stage.sh. exec, so the run keeps this pid.
SANDBOX_RUN_SH=$0 exec python3 "$(dirname "$0")/src/run.py" "$@"
