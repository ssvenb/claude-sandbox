#!/usr/bin/env python3
"""Carry a login a run refreshed back to your own ~/.claude, and nothing else of the run's copy.

    keep-credentials.py RUN_COPY/.credentials.json ~/.claude/.credentials.json

Runs on the HOST, after the container is gone. The run's file is the agent's to write, so it counts
only as a regular file (not a symlink, not a FIFO to hang on) of valid JSON whose claudeAiOauth holds
string tokens and a numeric expiresAt later than yours. Only that claudeAiOauth is taken; the rest
of your file stays as it is.
"""
import json
import os
import stat
import sys


def oauth(path, follow=True):
    """(the file's JSON, its claudeAiOauth) when it is a regular file holding a well-formed login, else None."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | (0 if follow else os.O_NOFOLLOW))
    except OSError:
        return None
    with os.fdopen(fd, "rb") as f:
        try:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                return None
            data = json.loads(f.read(1 << 20))
        except (OSError, ValueError):
            return None
    login = data.get("claudeAiOauth") if isinstance(data, dict) else None
    if not (isinstance(login, dict) and isinstance(login.get("accessToken"), str)
            and isinstance(login.get("refreshToken"), str)
            and isinstance(login.get("expiresAt"), (int, float)) and not isinstance(login.get("expiresAt"), bool)):
        return None
    return data, login


def keep(run_file, own_file):
    """Whether the run's login replaced yours."""
    theirs = oauth(run_file, follow=False)
    if theirs is None:
        return False
    mine = oauth(own_file)
    if mine is not None and theirs[1]["expiresAt"] <= mine[1]["expiresAt"]:
        return False
    data = mine[0] if mine is not None else {}
    tmp = f"{own_file}.sandbox.tmp"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump({**data, "claudeAiOauth": theirs[1]}, f)
    os.replace(tmp, own_file)
    return True


if __name__ == "__main__":
    keep(*sys.argv[1:3])
