# shellcheck shell=sh
# Agent stage: with homeInstalls, point npm's global prefix and pip's installs at the agent's home,
# so both work without root, with their bin dirs first on PATH. Then brief the agent on all of it.

if [ "${PERMISSIONS_HOME_INSTALLS:-0}" = 1 ]; then
  export NPM_CONFIG_PREFIX="$HOME/.npm-global"
  # pip falls back to a --user install when /usr is not writable; PEP 668 would refuse it on
  # Debian's externally managed python, but this is a throwaway container.
  export PIP_BREAK_SYSTEM_PACKAGES=1
  mkdir -p "$NPM_CONFIG_PREFIX/bin" "$HOME/.local/bin"
  export PATH="$NPM_CONFIG_PREFIX/bin:$HOME/.local/bin:$PATH"
fi

[ -n "${AGENT_PROMPT_FILE:-}" ] || return 0

if [ "${PERMISSIONS_SUDO:-0}" = 1 ]; then
  echo "You have passwordless \`sudo\` for any command in this sandbox." >> "$AGENT_PROMPT_FILE"
else
  # What root-init.sh actually allowed: the commands it found, as full paths.
  _perm_cmds=$(sudo -n -l 2>/dev/null | sed -n 's/^ *(root) NOPASSWD: //p')
  [ -z "$_perm_cmds" ] || echo "You have passwordless \`sudo\` for these only: $_perm_cmds." >> "$AGENT_PROMPT_FILE"
  unset _perm_cmds
fi
if [ "${PERMISSIONS_HOME_INSTALLS:-0}" = 1 ]; then
  echo "\`npm install -g <pkg>\` and \`pip install <pkg>\` install into your home directory (already on PATH), no root needed." >> "$AGENT_PROMPT_FILE"
fi
