#!/usr/bin/env python3
"""Claude Code hook: say in the terminal stream whether the agent is working, idle, or waiting on
an answer, for src/server/server.py to pick up and colour the session's dot with.

The state goes out as a user variable, `ESC ] 1337 ; SetUserVar=agent_status=<base64> BEL` (the
iTerm2/WezTerm convention): terminals that do not know it ignore it, xterm.js among them. Hooks
run with pipes for stdio, so it is written to the terminal of the nearest ancestor that has one —
the agent's own, which root-init.sh handed to this user.

With AGENT_STATUS_WEBHOOK set (host.sh, from the project's config), it also POSTs to that URL when
the state turns idle or question, once per change, in the shape AGENT_STATUS_WEBHOOK_TYPE names: the last state is kept in a file, as each hook
is a process of its own. The POST runs in a detached child, so a slow endpoint never holds up the agent.

Never in the way: whatever goes wrong, it prints nothing and exits 0.
"""
import base64
import json
import os
import sys
import tempfile
import urllib.request

# Tools that stop to ask the user something, and stay open until they answer.
ASKING = {"AskUserQuestion", "ExitPlanMode"}

# What the webhook says, for the states it is told about.
SAY = {"idle": "idle, waiting for its next task", "question": "needs you"}


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


def notify(state):
    url = os.environ.get("AGENT_STATUS_WEBHOOK")
    if not url:
        return
    last = os.path.join(tempfile.gettempdir(), "agent-status.last")
    try:
        with open(last) as f:
            if f.read() == state:
                return
    except OSError:
        pass
    with open(last, "w") as f:
        f.write(state)
    if state not in SAY or os.fork():
        return
    try:  # the child, off the hook's pipes so Claude Code does not wait for it; never returns
        os.setsid()
        null = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):
            os.dup2(null, fd)
        project, run = os.environ.get("AGENT_STATUS_PROJECT") or "sandbox", os.environ.get("RUN_ID", "")
        text = f"{project} ({run}): {SAY[state]}" if run else f"{project}: {SAY[state]}"
        body = {"text": text, "content": text, "project": project, "run_id": run, "status": state}
        if os.environ.get("AGENT_STATUS_WEBHOOK_TYPE") == "google-chat":
            body = {"text": text}  # Google's API refuses fields it does not know
        req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).close()
    finally:
        os._exit(0)


def main():
    state = status(json.load(sys.stdin))
    try:  # a broken webhook must not cost the status dot
        if state:
            notify(state)
    except Exception:
        pass
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
