#!/usr/bin/env python3
"""PreToolUse hook: keep the agent on its own per-run <agent>/<id> branch.

Reads the tool call as JSON on stdin. Exit 2 blocks the call.
"""
import json
import os
import shlex
import sys

data = json.load(sys.stdin)
cmd = data.get("tool_input", {}).get("command", "")

# AGENT_BRANCH and its prefix are exported by the git-workspace plugin before the agent
# starts, so they're inherited here. Fall back to the agent's own name if unset.
branch = os.environ.get("AGENT_BRANCH") or os.environ.get("AGENT", "claude")
prefix = os.environ.get("AGENT_BRANCH_PREFIX") or branch.split("/")[0]


def block(msg: str):
    print(msg, file=sys.stderr)
    sys.exit(2)


# Branch switching/creation is always blocked: the agent stays on the branch
# agent-setup.sh checked out for it.
if any(op in cmd for op in
       ("git checkout", "git switch", "git branch", "git worktree")):
    block(f"Blocked: this agent is restricted to its own {branch} branch.")

if "git push" in cmd:
    # First positional token after `git push` (skipping flags and the remote) is the
    # refspec. A bare push has none and targets the current branch — always $branch,
    # since switching is blocked above — so it's allowed.
    rest = shlex.split(cmd.split("git push", 1)[1])
    ref = next((t for t in rest if not t.startswith("-") and t != "origin"), "")
    # An explicit ref must be this run's own branch, by resolved value or via the
    # $AGENT_BRANCH / <prefix>/$RUN_ID variable forms the agent is told to use. The prefix is
    # the agent's own (git-workspace exports it from agents/<name>/agent.json).
    allowed = {branch, f"HEAD:{branch}", f"{branch}:{branch}", f"refs/heads/{branch}",
               "$AGENT_BRANCH", "${AGENT_BRANCH}",
               f"{prefix}/$RUN_ID", f"{prefix}/${{RUN_ID}}"}
    if ref and ref not in allowed:
        block(f"Blocked: this agent may only push its own {branch} branch (got: {ref}).")
