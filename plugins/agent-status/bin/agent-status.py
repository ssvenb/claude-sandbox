#!/usr/bin/env python3
"""Claude Code hook: say in the terminal stream whether the agent is working, idle, or waiting on
an answer, for src/server/server.py to pick up and colour the session's dot with.

The state goes out as a user variable, `ESC ] 1337 ; SetUserVar=agent_status=<base64> BEL` (the
iTerm2/WezTerm convention): terminals that do not know it ignore it, xterm.js among them. Hooks
run with pipes for stdio, so it is written to the terminal of the nearest ancestor that has one —
the agent's own, which root-init.sh handed to this user.

Never in the way: whatever goes wrong, it prints nothing and exits 0.
"""
import base64
import json
import os
import sys

# Tools that stop to ask the user something, and stay open until they answer.
ASKING = {"AskUserQuestion", "ExitPlanMode"}


def status(event):
    name, tool = event.get("hook_event_name"), event.get("tool_name")
    if name == "Stop":
        return "idle"
    if name == "Notification":
        kind = event.get("notification_type")
        if kind == "idle_prompt":
            return "idle"
        if kind in ("permission_prompt", "elicitation_dialog") or "permission" in event.get("message", ""):
            return "question"
        return None
    if name == "PreToolUse" and tool in ASKING:
        return "question"
    if name in ("UserPromptSubmit", "PreToolUse", "PostToolUse"):
        return "working"
    return None


def terminal():
    pid = os.getppid()
    while pid > 1:
        try:
            path = os.readlink(f"/proc/{pid}/fd/1")
            if path.startswith("/dev/pts/"):
                return path
            with open(f"/proc/{pid}/stat") as f:
                pid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            return None
    return None


def main():
    state = status(json.load(sys.stdin))
    path = state and terminal()
    if not path:
        return
    fd = os.open(path, os.O_WRONLY | os.O_NOCTTY)
    try:  # in one write, which the pty keeps whole
        os.write(fd, b"\x1b]1337;SetUserVar=agent_status=" + base64.b64encode(state.encode()) + b"\x07")
    finally:
        os.close(fd)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
