# shellcheck shell=sh
# Root stage: start the sandbox's own Docker daemon. Root here is an unprivileged user on the host
# (Sysbox maps it), and Sysbox gives /var/lib/docker a volume of its own, so dockerd runs as usual.

[ -x /usr/bin/dockerd ] || return 0

dockerd >/var/log/dockerd.log 2>&1 &
_dockerd=$! _i=0
# Up to 30s; a daemon that exits (no Sysbox under it) ends the wait at once.
until docker info >/dev/null 2>&1; do
  _i=$((_i + 1))
  if [ "$_i" -ge 30 ] || ! kill -0 "$_dockerd" 2>/dev/null; then
    echo "⚠️  Docker daemon did not start; see /var/log/dockerd.log" >&2
    _dockerd=
    break
  fi
  sleep 1
done
[ -z "$_dockerd" ] || echo "🐳 Docker daemon running, this sandbox's own"
unset _dockerd _i
