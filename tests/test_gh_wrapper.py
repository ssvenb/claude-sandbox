"""github-auth's bin/gh: which token gh runs with, by the repo it acts on (#85)."""
import os
import subprocess

import pytest

from conftest import REPO

OWN = "https://github.com/Acme/widgets.git"


@pytest.fixture
def gh(tmp_path):
    real = tmp_path / "real-gh"
    real.write_text('#!/bin/sh\necho "${GH_TOKEN:-login}"\n')
    real.chmod(0o755)
    all_token = tmp_path / "all"
    all_token.write_text("ghs_all\n")
    script = (REPO / "plugins/github-auth/bin/gh").read_text()
    script = script.replace("real=/usr/bin/gh", f"real={real}").replace(
        "all=/run/credentials/github-token-all", f"all={all_token}")
    wrapper = tmp_path / "gh"
    wrapper.write_text(script)
    wrapper.chmod(0o755)
    other = tmp_path / "other"
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    subprocess.run(["git", "-C", str(other), "remote", "add", "origin", "git@github.com:acme/other.git"], check=True)
    own = tmp_path / "own"
    subprocess.run(["git", "init", "-q", str(own)], check=True)
    subprocess.run(["git", "-C", str(own), "remote", "add", "origin", OWN], check=True)

    def call(*args, cwd=own, repo_url=OWN):
        env = {**os.environ, "REPO_URL": repo_url}
        env.pop("GH_TOKEN", None)
        return subprocess.run([str(wrapper), *args], cwd=cwd, env=env, capture_output=True, text=True,
                              check=True).stdout.strip()
    call.other = other
    return call


@pytest.mark.parametrize("args, token", [
    (["pr", "create"], "login"),
    (["issue", "create", "--repo", "acme/widgets"], "login"),
    (["issue", "create", "--repo", "ssvenb/claude-sandbox"], "ghs_all"),
    (["issue", "list", "-Rssvenb/claude-sandbox"], "ghs_all"),
    (["issue", "list", "--repo=https://github.com/acme/WIDGETS"], "login"),
    (["api", "-X", "POST", "repos/acme/widgets/pulls"], "login"),
    (["api", "/repos/acme/other/issues"], "ghs_all"),
    (["repo", "view", "acme/other"], "ghs_all"),
    (["auth", "status"], "login"),
])
def test_token_follows_the_target_repo(gh, args, token):
    assert gh(*args) == token


def test_another_checkout_and_no_own_repo_get_the_all_token(gh):
    assert gh("pr", "list", cwd=gh.other) == "ghs_all"
    assert gh("pr", "list", repo_url="") == "ghs_all"
