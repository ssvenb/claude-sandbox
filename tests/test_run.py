"""run.sh end to end, with `docker` replaced by a stub that records its command lines."""
import glob
import json
import os
import re
import socket
import subprocess
from datetime import datetime, timezone

import pytest

from conftest import REPO

# Everything that needs the network, a GitHub App or a Docker socket is off; what is left on is
# the default set minus those.
BASE = {"env": {"AGENT_VERSION": "1.2.3"}, "plugins": {
    "github-auth": {"enabled": False}, "git-workspace": {"enabled": False},
    "agent-workspace": {"enabled": False}, "docker-cli": {"enabled": False},
    "claude-home": {"enabled": False}, "cwd-workspace": {"enabled": True}}}


@pytest.fixture
def run_sh(sb, short_tmp):
    log = sb.tmp / "docker-calls"
    log.mkdir()
    sb.stub("docker", f'n=$(ls "{log}" | wc -l)\nprintf "%s\\0" "$@" >"{log}/$n"\n'
                      '[ "$1" != info ] || echo "Ubuntu 24.04 LTS"\n')
    sb.env["TMPDIR"] = str(short_tmp)

    def run(*args, config=BASE, timeout=60, **env):
        if config is not None:
            sb.config(config)
        done = subprocess.run([REPO / "run.sh", *args], cwd=sb.cwd, env=sb._env(env),
                              capture_output=True, text=True, timeout=timeout)
        done.calls = [(log / str(i)).read_text().split("\0")[:-1] for i in range(len(os.listdir(log)))]
        return done
    return run


def calls(done, command):
    return [c for c in done.calls if c[0] == command]


def test_the_host_pipeline_builds_and_runs_the_image(sb, run_sh):
    sb.dotenv("CLAUDE_CODE_OAUTH_TOKEN=oauth-tok\nCLAUDE_EFFORT=high\nAPI_SECRET=hunter2\n")
    done = run_sh()
    assert done.returncode == 0, done.stderr
    [build], [run] = calls(done, "build"), calls(done, "run")
    plugins = ("herdr host-network data-mounts upstream-proxy cwd-workspace package-managers "
               "project-deps branch-guard")
    assert build == ["build", "-t", "claude-agent:claude", "--build-arg", "AGENT=claude",
                     "--build-arg", "AGENT_VERSION=1.2.3", "--build-arg", f"ENABLED_PLUGINS={plugins}", "."]
    run_id = re.fullmatch(r"RUN_ID=([0-9a-f]{6})", run[4])[1]
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    assert run[:13] == ["run", "-it", "--rm", "-e", f"RUN_ID={run_id}", "-e", f"RUN_DATE={today}",
                        "-e", "RESUME=0", "-e", "AGENT=claude", "-e", f"ENABLED_PLUGINS={plugins}"]
    assert run[-1] == "claude-agent:claude"
    tail = " ".join(run[13:])
    for expected in ("--network host", f"-v {sb.cwd}:/workspace", "-v /dev/null:/workspace/.env:ro",
                     "-e CWD_WORKSPACE_HIDDEN=/workspace/.env",
                     "-e CLAUDE_CODE_OAUTH_TOKEN=oauth-tok", "-e CLAUDE_EFFORT=high"):
        assert expected in tail
    # The repo's own secret is neither a sandbox setting nor forwarded anywhere.
    assert not any("hunter2" in arg for call in done.calls for arg in call)
    assert f"🔌 Plugins: {plugins}" in done.stdout


def test_resume_reuses_the_run_id(sb, run_sh):
    done = run_sh("--resume", "0a1b2c", CLAUDE_CODE_OAUTH_TOKEN="t")
    [run] = calls(done, "run")
    assert "RUN_ID=0a1b2c" in run and "RESUME=1" in run


def test_run_id_starts_a_fresh_run_under_the_given_id(sb, run_sh):
    done = run_sh("--run-id", "0a1b2c", CLAUDE_CODE_OAUTH_TOKEN="t")
    [run] = calls(done, "run")
    assert "RUN_ID=0a1b2c" in run and "RESUME=0" in run
    assert run[-3:-1] == ["--name", "sandbox-0a1b2c"]


@pytest.mark.parametrize("args, code, message", [
    (["--run-id", "nothex"], 1, "Invalid RUN_ID 'nothex'"),
    (["--resume", "ABC123"], 1, "Invalid RUN_ID 'ABC123'"),
    (["--resume", "abc12"], 1, "Invalid RUN_ID"),
    (["--bogus"], 1, "Unknown argument: --bogus"),
    (["--help"], 0, "Usage:"),
    (["--resume"], 1, "Invalid RUN_ID ''"),
])
def test_command_line(run_sh, args, code, message):
    done = run_sh(*args, timeout=15)
    assert (done.returncode, done.calls) == (code, [])
    assert message in done.stderr


def test_the_agent_is_chosen_per_project(sb, run_sh):
    (sb.home / ".copilot").mkdir()
    config = json.loads(json.dumps(BASE))
    config["env"]["AGENT"] = "copilot"
    done = run_sh(config=config)
    assert done.returncode == 0, done.stderr
    [build], [run] = calls(done, "build"), calls(done, "run")
    assert build[:5] == ["build", "-t", "claude-agent:copilot", "--build-arg", "AGENT=copilot"]
    plugins = dict(a.split("=", 1) for a in build if a.startswith("ENABLED_PLUGINS="))["ENABLED_PLUGINS"].split()
    assert "copilot-home" in plugins and "branch-guard" not in plugins and "claude-home" not in plugins
    assert f"{sb.home}/.copilot:/home/node/.copilot" in run
    assert run[-1] == "claude-agent:copilot"


def test_configuration_errors_stop_the_run_before_docker(run_sh):
    done = run_sh(config={"env": {"NOT_A_SETTING": "1"}})
    assert done.returncode == 1 and done.calls == []
    assert "is not a sandbox setting" in done.stderr


def test_unmet_capabilities_stop_the_run_before_docker(run_sh):
    config = json.loads(json.dumps(BASE))
    config["plugins"]["cwd-workspace"]["enabled"] = False
    done = run_sh(config=config, CLAUDE_CODE_OAUTH_TOKEN="t")
    assert done.returncode == 1 and done.calls == []
    assert "Plugin 'branch-guard' requires the 'workspace' capability. Enable one of: cwd-workspace,git-workspace" \
        in done.stderr


def test_host_proxy_runs_exactly_as_long_as_the_container(sb, run_sh, short_tmp):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    config = json.loads(json.dumps(BASE))
    config["plugins"]["upstream-proxy"] = {"routes": [{"name": "api", "port": port,
                                                       "upstream": "http://127.0.0.1:9"}]}
    done = run_sh(config=config, CLAUDE_CODE_OAUTH_TOKEN="t")
    assert done.returncode == 0, done.stderr
    [run] = calls(done, "run")
    assert "UPSTREAM_PROXY_PORTS=api:" + str(port) in run
    assert "UPSTREAM_PROXY_ATTEST_DIR=/run/upstream-proxy-attest" in run  # host-network is on
    [proxy_dir] = glob.glob(f"{short_tmp}/upstream-proxy-*")
    assert os.listdir(proxy_dir) == ["lock"], "the proxy outlived run.sh"
