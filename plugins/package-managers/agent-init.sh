# shellcheck shell=sh
# Agent stage: point npm's global prefix and pip's installs at the agent's home, so both work
# without root, and put their bin dirs first on PATH for the agent that launches after this.

export NPM_CONFIG_PREFIX="$HOME/.npm-global"
# pip falls back to a --user install when /usr is not writable; PEP 668 would refuse it on Debian's
# externally managed python, but this is a throwaway container.
export PIP_BREAK_SYSTEM_PACKAGES=1
mkdir -p "$NPM_CONFIG_PREFIX/bin" "$HOME/.local/bin"
export PATH="$NPM_CONFIG_PREFIX/bin:$HOME/.local/bin:$PATH"

[ -n "${AGENT_PROMPT_FILE:-}" ] || return 0

cat >> "$AGENT_PROMPT_FILE" <<'BRIEF'

You may install whatever tools you need: `npm install -g <pkg>` and `pip install <pkg>` install
into your home directory (already on PATH), and `sudo apt-get update && sudo apt-get install -y
<pkg>` installs system packages. Installs last only for this container's lifetime.
BRIEF
