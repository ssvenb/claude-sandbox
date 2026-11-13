# shellcheck shell=sh
# Root stage: give the agent user its own terminal, as a login would. docker's pty is root:tty
# 0620, and Claude Code runs hooks with pipes for stdio, so without this the status hook has no way
# to reach the terminal the web UI reads. Owning the pty it already writes its TUI to grants nothing
# new. No terminal (`docker run` without -t): nothing to report to, nothing to do.
if _tty=$(tty 2>/dev/null); then
  chown node "$_tty" 2>/dev/null || echo "⚠️  agent-status: could not hand $_tty to node" >&2
fi
unset _tty
