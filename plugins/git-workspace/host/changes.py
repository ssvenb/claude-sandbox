#!/usr/bin/env python3
"""The files a run's checkout changed since it branched off its base, committed or not, as a JSON
array on stdout: each {path, status (A, M or D), added, removed}, the lines added and removed being
null for a binary file. Run by the web server in the checkout (web_command in ../web.sh).

    changes.py [BASE_BRANCH]    (default: origin's default branch, else main or master)
"""
import json
import subprocess
import sys
from pathlib import Path


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout


def changes(base_branch=""):
    tips = [f"origin/{base_branch}", base_branch] if base_branch else ["origin/HEAD", "origin/main", "main", "origin/master", "master"]
    main = next((b for b in tips if git("rev-parse", "-q", "--verify", b + "^{commit}")), "HEAD")
    base = git("merge-base", "HEAD", main).strip() or "HEAD"
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


if __name__ == "__main__":
    json.dump(changes(*sys.argv[1:2]), sys.stdout)
