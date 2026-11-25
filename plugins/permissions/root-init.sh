# shellcheck shell=sh
# Root stage: the sudoers rule for what the project allows: everything ($PERMISSIONS_SUDO), or the
# commands of the tools in $PERMISSIONS_TOOLS. Nothing allowed, no rule: sudo refuses.

_perm_rule=""
if [ "${PERMISSIONS_SUDO:-0}" = 1 ]; then
  _perm_rule=ALL
else
  for _perm_tool in ${PERMISSIONS_TOOLS:-}; do
    case $_perm_tool in
      apt) _perm_cmds="apt apt-get dpkg" ;;
      pip) _perm_cmds="pip pip3" ;;
      chown) _perm_cmds="chown chmod" ;;
      mount) _perm_cmds="mount umount" ;;
      network) _perm_cmds="ip iptables ip6tables" ;;
      *) _perm_cmds=$_perm_tool ;;
    esac
    for _perm_cmd in $_perm_cmds; do
      # sudoers wants full paths; a tool the image lacks is left out rather than break the file.
      _perm_path=$(command -v "$_perm_cmd") || { echo "⚠️  permissions: $_perm_cmd not found" >&2; continue; }
      _perm_rule="${_perm_rule:+$_perm_rule, }$_perm_path"
    done
  done
fi

if [ -n "$_perm_rule" ]; then
  # PEP 668 would refuse a root pip install into Debian's python; this is a throwaway container.
  printf '[global]\nbreak-system-packages = true\n' > /etc/pip.conf
  echo "node ALL=(root) NOPASSWD: $_perm_rule" > /etc/sudoers.d/permissions
  chmod 440 /etc/sudoers.d/permissions
  visudo -cqf /etc/sudoers.d/permissions || { echo "⚠️  permissions: bad sudoers rule, removed" >&2; rm -f /etc/sudoers.d/permissions; }
  echo "🔑 permissions: node may sudo $_perm_rule"
fi
unset _perm_rule _perm_tool _perm_cmds _perm_cmd _perm_path
