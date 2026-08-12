# shellcheck shell=bash
# Host stage: give the container access to a Docker daemon by mounting its socket.

pass_mount /var/run/docker.sock /var/run/docker.sock
