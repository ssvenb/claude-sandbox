# shellcheck shell=bash
# Host stage: give the container access to a Docker daemon by mounting its socket.

[ -S /var/run/docker.sock ] \
  || die "/var/run/docker.sock not found — no Docker daemon to reach (disable the plugin with ENABLE_DOCKER_CLI=0)"

pass_mount /var/run/docker.sock /var/run/docker.sock

# A bind mount carries the host's numeric owner through, so the agent user can only reach the
# socket via a group with that exact gid. root-init.sh needs the number.
pass_value DOCKER_SOCKET_GID "$(stat -c '%g' /var/run/docker.sock)"
