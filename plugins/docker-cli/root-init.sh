# shellcheck shell=sh
# Root stage: make the mounted socket usable by the agent user.
#
# The bind mount keeps the host's numeric owner (root:<host docker gid>, mode 0660), and that gid
# almost never exists in the container — so `docker ps` as 'node' fails with "permission denied
# while trying to connect to the Docker daemon socket". Runs as root because only root may create
# a group and change 'node''s membership; the added group grants nothing beyond the socket.

if [ -n "${DOCKER_SOCKET_GID:-}" ]; then
  # Reuse whatever group already holds that gid (Debian's own 'docker' group would, on a rebuild),
  # otherwise create one.
  _docker_group=$(getent group "$DOCKER_SOCKET_GID" | cut -d: -f1)
  if [ -z "$_docker_group" ]; then
    _docker_group=docker-host
    groupadd -g "$DOCKER_SOCKET_GID" "$_docker_group" 2>/dev/null \
      || echo "⚠️  Could not create group $_docker_group (gid $DOCKER_SOCKET_GID)" >&2
  fi
  if id -nG node | tr ' ' '\n' | grep -qx "$_docker_group"; then
    :
  else
    usermod -aG "$_docker_group" node \
      && echo "🐳 Docker socket: node added to $_docker_group (gid $DOCKER_SOCKET_GID)" \
      || echo "⚠️  Could not add node to $_docker_group" >&2
  fi
  unset _docker_group
fi
