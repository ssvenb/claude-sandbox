"""plugins/branch-guard/bin/guard-branch.py: the PreToolUse hook that pins the agent to its branch."""
import json
import subprocess

import pytest

from conftest import REPO

HOOK = REPO / "plugins/branch-guard/bin/guard-branch.py"
BRANCH = "claude-code/20260102-abc123"


def guard(command, **env):
    env = {"AGENT_BRANCH": BRANCH, "AGENT_BRANCH_PREFIX": "claude-code", **env}
    env = {k: v for k, v in env.items() if v is not None}
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    return subprocess.run([HOOK], input=payload, capture_output=True, text=True, env=env)


@pytest.mark.parametrize("command", [
    "git checkout main",
    "git checkout -b other",
    "git switch -c other",
    "git branch -D old",
    "git worktree add ../elsewhere",
    "cd /workspace && git checkout -- file.txt",
])
def test_branch_switching_is_always_blocked(command):
    done = guard(command)
    assert done.returncode == 2
    assert BRANCH in done.stderr


@pytest.mark.parametrize("command", [
    "git push origin main",
    "git push -u origin other",
    "git push --force origin main",
    "git push origin HEAD:main",
    "git push origin claude-code/20260102-ffffff",
    "git push origin refs/heads/main",
])
def test_push_to_another_branch_is_blocked(command):
    done = guard(command)
    assert done.returncode == 2
    assert "may only push" in done.stderr


@pytest.mark.parametrize("command", [
    "git status",
    "git commit -m 'checkout notes'",
    "git push",
    "git push --force-with-lease",
    f"git push origin {BRANCH}",
    f"git push -u origin {BRANCH}",
    f"git push origin HEAD:{BRANCH}",
    f"git push origin {BRANCH}:{BRANCH}",
    f"git push origin refs/heads/{BRANCH}",
    'git push origin "$AGENT_BRANCH"',
    "git push origin ${AGENT_BRANCH}",
    "git push origin claude-code/$RUN_ID",
    "git push origin claude-code/${RUN_ID}",
])
def test_own_branch_and_unrelated_commands_pass(command):
    done = guard(command)
    assert done.returncode == 0, done.stderr


def test_without_git_workspace_it_falls_back_to_the_agent_name():
    assert guard("git push origin copilot", AGENT_BRANCH=None, AGENT_BRANCH_PREFIX=None,
                 AGENT="copilot").returncode == 0
    assert guard("git push origin main", AGENT_BRANCH=None, AGENT_BRANCH_PREFIX=None,
                 AGENT="copilot").returncode == 2


def test_an_unparsable_push_is_blocked_not_waved_through():
    """A crash would exit 1, which Claude Code treats as non-blocking: the push would run."""
    done = guard("git push origin main && echo it's done")
    assert done.returncode == 2
    assert "could not parse" in done.stderr
