# shellcheck shell=bash
# Host stage: run the sandbox under Sysbox, so the agent gets a Docker daemon of its own inside it.
# Never the host's socket: with it the agent could reach every other sandbox and be root on the host.

docker info --format '{{range $name, $_ := .Runtimes}}{{$name}} {{end}}' 2>/dev/null | grep -qw sysbox-runc \
  || die "docker-cli needs the Sysbox runtime (sysbox-runc) on this host, to give the sandbox a Docker daemon of its own: install it (https://github.com/nestybox/sysbox), or disable the plugin with ENABLE_DOCKER_CLI=0"

pass_arg --runtime=sysbox-runc
