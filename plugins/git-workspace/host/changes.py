#!/usr/bin/env python3
"""The files a run's checkout changed since it branched off its base, committed or not, as a JSON
array on stdout: each {path, status (A, M or D), added, removed}, the lines added and removed being
null for a binary file. Asked for by the web server (web_command in ../web.sh), which names the
run in WEB_RUN_ID: then this script runs itself inside that run's container, never on this machine.
The checkout is the agent's, .git/config included, and git runs what that config says (core.fsmonitor,
a diff or filter driver): run here, as you, that would be anything the agent wrote there.

    changes.py [BASE_BRANCH]    (default: origin's default branch, else main or master)
"""
import json
import os
import subprocess
import sys
from pathlib import Path


def git(*args, check=True):
    """git's output; with `check`, its failure (not a repository, dubious ownership) an error, never
    an empty answer that would read as "no changes"."""
    done = subprocess.run(["git", *args], capture_output=True, text=True)
    if check and done.returncode:
        sys.exit(f"changes.py: git {args[0]}: {(done.stderr.strip().splitlines() or ['failed'])[0]}")
    return done.stdout


def changes(base_branch=""):
    tips = [f"origin/{base_branch}", base_branch] if base_branch else ["origin/HEAD", "origin/main", "main", "origin/master", "master"]
    main = next((b for b in tips if git("rev-parse", "-q", "--verify", b + "^{commit}", check=False)), None)
    # No branch to have left (a repo of the run's own, git-workspace's for a project with no repo,
    # with no remote and only the run's branch), or none in common with it: all it has is changed,
    # committed or not, even before its first commit.
    base = (main and git("merge-base", "HEAD", main, check=False).strip()) \
        or git("hash-object", "-t", "tree", "/dev/null").strip()  # the empty tree
    found = {}
    status = git("diff", "--no-renames", "--name-status", "-z", base).split("\0")
    for kind, path in zip(status[::2], status[1::2]):
        found[path] = {"path": path, "status": kind[:1], "added": None, "removed": None}
    for line in git("diff", "--no-renames", "--numstat", "-z", base).split("\0"):
        added, removed, path = (line.split("\t", 2) + ["", ""])[:3]
        if path in found and added != "-":
            found[path] |= {"added": int(added), "removed": int(removed)}
    for path in filter(None, git("ls-files", "-z", "--others", "--exclude-standard").split("\0")):
        try:
            data = Path(path).read_bytes()
        except OSError:  # gone again, or a directory (a nested repo)
            continue
        found[path] = {"path": path, "status": "A", "removed": 0,
                       "added": None if b"\0" in data else data.count(b"\n") + (not data.endswith(b"\n") and bool(data))}
    return sorted(found.values(), key=lambda f: f["path"])


def in_container(run_id, args):
    """This script, fed on stdin to python3 in the run's container, as its agent user, in /workspace."""
    with open(__file__, "rb") as me:
        return subprocess.run(["docker", "exec", "-i", "-u", "node", "-w", "/workspace", f"sandbox-{run_id}",
                               "python3", "-", *args], stdin=me, check=False).returncode


if __name__ == "__main__":
    if run_id := os.environ.get("WEB_RUN_ID"):
        sys.exit(in_container(run_id, sys.argv[1:2]))
    json.dump(changes(*sys.argv[1:2]), sys.stdout)
