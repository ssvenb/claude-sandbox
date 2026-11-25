"""plugins/git-workspace/bin/hooks/: the branch guard, as git runs it for every agent."""
import os
import subprocess

from conftest import REPO

HOOKS = REPO / "plugins/git-workspace/bin/hooks"
BRANCH = "claude-code/20260102-abc123"
BASE = {"PATH": os.environ["PATH"], "HOME": "/nonexistent", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
GUARDED = {**BASE, "AGENT_BRANCH": BRANCH,  # what agent-init.sh exports when branchGuard is on
           "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": str(HOOKS)}


def git(*args, cwd, env=GUARDED, check=True):
    return subprocess.run(["git", *map(str, args)], cwd=cwd, env=env, check=check, capture_output=True, text=True)


def clone(tmp_path):
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    git("init", "-q", "--bare", "-b", "main", origin, cwd=tmp_path, env=BASE)
    git("clone", "-q", origin, work, cwd=tmp_path, env=BASE)
    git("switch", "-q", "-c", BRANCH, cwd=work)
    git("commit", "-q", "--allow-empty", "-m", "work", cwd=work)
    return work


def test_only_the_runs_own_branch_is_pushed(tmp_path):
    work = clone(tmp_path)
    assert git("push", "-q", "origin", BRANCH, cwd=work).returncode == 0
    for ref in ("HEAD:main", f"{BRANCH}:other", "HEAD:refs/heads/main"):
        done = git("push", "origin", ref, cwd=work, check=False)
        assert done.returncode and f"may only push its own branch {BRANCH}" in done.stderr
    done = git("push", "origin", BRANCH, "HEAD:main", cwd=work, check=False)  # one bad ref fails it all
    assert done.returncode
    assert git("ls-remote", "--heads", "origin", cwd=work).stdout.count("refs/heads/") == 1


def test_without_the_guard_git_runs_no_hook_of_ours(tmp_path):
    work = clone(tmp_path)
    assert git("push", "-q", "origin", "HEAD:main", cwd=work, env=BASE).returncode == 0


def test_the_repos_own_hooks_still_run(tmp_path):
    """A repo's core.hooksPath (husky's .husky) is outranked, but its hooks run after ours."""
    work = clone(tmp_path)
    own = work / ".husky"
    own.mkdir()
    (own / "pre-commit").write_text("#!/bin/sh\ntouch ran-pre-commit\n")
    (own / "pre-push").write_text("#!/bin/sh\ncat > pushed-refs\nexit 1\n")
    for hook in own.iterdir():
        hook.chmod(0o755)
    git("config", "core.hooksPath", ".husky", cwd=work)
    git("commit", "-q", "--allow-empty", "-m", "more", cwd=work)
    assert (work / "ran-pre-commit").exists()
    assert git("push", "origin", BRANCH, cwd=work, check=False).returncode  # the repo's own refused it
    assert f"refs/heads/{BRANCH} " in (work / "pushed-refs").read_text()  # handed the same refs


def test_a_repo_without_hooks_of_its_own_commits_as_usual(tmp_path):
    work = clone(tmp_path)
    assert git("commit", "-q", "--allow-empty", "-m", "x", cwd=work).returncode == 0
