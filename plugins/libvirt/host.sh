# shellcheck shell=bash
# Host stage: give the container the host's system libvirt daemon(s) by mounting their sockets.
#
# On a modular host (virtqemud & co., the default on current Fedora/RHEL/Debian) each driver's
# socket is mounted where the client looks for it, so qemu:///system reaches virtqemud directly,
# just as it does on the host. The proxy socket (virtproxyd) is deliberately not used there: it
# fails to identify a caller from another PID namespace ("Cannot find start time for pid ..."). A
# monolithic libvirtd has only libvirt-sock, which is mounted instead. Admin sockets never cross.
#
# The sockets are 0666 and libvirt authorises by the caller's host uid (polkit), so the agent gets
# exactly what the host user running this has — with the stock libvirt group rule, full control of
# every VM, pool and network on the host.

_libvirt_mounted=0
for _sock in virtqemud virtstoraged virtnetworkd virtnodedevd virtinterfaced virtnwfilterd virtsecretd; do
  [ -S "/run/libvirt/$_sock-sock" ] || continue
  pass_mount "/run/libvirt/$_sock-sock" "/run/libvirt/$_sock-sock"
  _libvirt_mounted=1
done
if [ "$_libvirt_mounted" = 0 ] && [ -S /run/libvirt/libvirt-sock ]; then
  pass_mount /run/libvirt/libvirt-sock /run/libvirt/libvirt-sock
  _libvirt_mounted=1
fi
[ "$_libvirt_mounted" = 1 ] \
  || die "no libvirt socket under /run/libvirt — libvirt not installed, or its sockets (virtqemud.socket, or libvirtd.socket) not enabled (disable the plugin with ENABLE_LIBVIRT=0)"
unset _libvirt_mounted _sock

pass_value LIBVIRT_DEFAULT_URI qemu:///system
