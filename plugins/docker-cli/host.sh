# shellcheck shell=bash
# Host stage: give the container access to a Docker daemon by mounting its socket.

[ -S /var/run/docker.sock ] \
  || die "/var/run/docker.sock not found — no Docker daemon to reach (disable the plugin with ENABLE_DOCKER_CLI=0)"

pass_mount /var/run/docker.sock /var/run/docker.sock

# The socket is root:docker 0660 on the host, and a bind mount carries the host's numeric owner
# straight through — so the agent user only gets to talk to the daemon if it is a member of a
# group with that exact gid inside the container. Pass the number along for root-init.sh.
pass_value DOCKER_SOCKET_GID "$(stat -c '%g' /var/run/docker.sock)"
