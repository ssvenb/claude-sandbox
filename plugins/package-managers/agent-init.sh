# shellcheck shell=sh
# Agent stage: point npm's global prefix and pip's installs at the agent's home, so both work
# without root, and put their bin dirs first on PATH for the agent that launches after this. The
# same for what apt-home unpacks into ~/.local: its programs and their libraries.

export NPM_CONFIG_PREFIX="$HOME/.npm-global"
# pip falls back to a --user install when /usr is not writable; PEP 668 would refuse it on Debian's
# externally managed python, but this is a throwaway container.
export PIP_BREAK_SYSTEM_PACKAGES=1
mkdir -p "$NPM_CONFIG_PREFIX/bin" "$HOME/.local/bin"
export PATH="$NPM_CONFIG_PREFIX/bin:$HOME/.local/bin:$HOME/.local/usr/bin:$HOME/.local/usr/sbin:$PATH"
# apt-home only unpacks libraries the image lacks, so these never shadow a system one.
_triplet="$(uname -m)-linux-gnu"
export LD_LIBRARY_PATH="$HOME/.local/usr/lib/$_triplet:$HOME/.local/lib/$_triplet:$HOME/.local/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
unset _triplet

[ -n "${AGENT_PROMPT_FILE:-}" ] || return 0

cat >> "$AGENT_PROMPT_FILE" <<'BRIEF'

You may install whatever tools you need: `npm install -g <pkg>` and `pip install <pkg>` install
into your home directory (already on PATH), and `apt-home <pkg>...` installs Debian packages there
too, with their dependencies. There is no root and no sudo: apt-home only unpacks packages, so
their install scripts never run, and services or setup a package expects from them won't happen.
Installs last only for this container's lifetime.
BRIEF
