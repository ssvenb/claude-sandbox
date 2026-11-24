"""run.sh end to end, with `docker` replaced by a stub that records its command lines."""
import glob
import json
import os
import re
import signal
import socket
import subprocess
import time
from datetime import datetime, timezone

import pytest

from conftest import REPO

# Everything that needs the network, a GitHub App or a Docker socket is off; what is left on is
# the default set minus those.
BASE = {"env": {"AGENT_VERSION": "1.2.3", "CLAUDE_HOME_MOUNT": "0"}, "plugins": {
    "github-auth": {"enabled": False}, "git-workspace": {"enabled": False},
    "agent-workspace": {"enabled": False}, "docker-cli": {"enabled": False},
    "cwd-workspace": {"enabled": True}}}


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
    sb.dotenv("API_SECRET=hunter2\nCLAUDE_EFFORT=low\n")  # the repo's own: not read
    auth = sb.tmp / "auth.json"  # the token is an authentication the project only names
    auth.write_text(json.dumps({"max": {"type": "claude-token", "token": "oauth-tok"}}))
    auth.chmod(0o600)
    done = run_sh(config={**BASE, "env": {**BASE["env"], "CLAUDE_AUTH": "max", "CLAUDE_EFFORT": "high"}},
                  SANDBOX_AUTH_FILE=auth)
    assert done.returncode == 0, done.stderr
    [build], [run] = calls(done, "build"), calls(done, "run")
    plugins = ("herdr data-mounts upstream-proxy cwd-workspace build-tools package-managers "
               "project-deps dev-server agent-status branch-guard")
    assert build == ["build", "-t", "claude-agent:claude", "--build-arg", "AGENT=claude",
                     "--build-arg", "AGENT_VERSION=1.2.3", "--build-arg", f"ENABLED_PLUGINS={plugins}", "."]
    run_id = re.fullmatch(r"RUN_ID=([0-9a-f]{6})", run[4])[1]
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    assert run[:15] == ["run", "-it", "--rm", "-e", f"RUN_ID={run_id}", "-e", f"RUN_DATE={today}",
                        "-e", "RESUME=0", "-e", "AGENT=claude", "-e", f"HOST_UID={os.getuid()}",
                        "-e", f"ENABLED_PLUGINS={plugins}"]
    assert run[-1] == "claude-agent:claude"
    tail = " ".join(run[13:])
    assert "--network" not in run and not any(a.startswith("-p") for a in run)  # publishes nothing
    for expected in (f"-v {sb.cwd}:/workspace", "-v /dev/null:/workspace/.env:ro",
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
    (["--task"], 1, "--task needs the task's text."),
    (["--resume", "0a1b2c", "--task", "Fix it"], 1, "--task starts a fresh run"),
    (["--chat", "--task", "Fix it"], 1, "--chat takes its prompts as commands"),
    (["--set", "CLAUDE_EFFORT"], 1, "--set needs NAME=VALUE."),
    (["--set", "API_SECRET=1"], 1, "--set API_SECRET: not a sandbox setting"),
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
    assert "copilot-home" in plugins and "branch-guard" not in plugins
    assert any(a.startswith(f"{sb.home}/.local/state/claude-sandbox/copilot-home/") and a.endswith(":/home/node/.copilot")
               for a in run)  # the run's copy of ~/.copilot, not yours
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
    [proxy_dir] = glob.glob(f"{short_tmp}/upstream-proxy-*")
    assert os.listdir(proxy_dir) == ["lock"], "the proxy outlived run.sh"


def test_web_describes_the_project_and_starts_nothing(sb, run_sh):
    # Its settings are announced on a normal run: that must not leak into the JSON.
    done = run_sh("--web", config={**BASE, "env": {**BASE["env"], "CLAUDE_EFFORT": "high"}})
    assert done.returncode == 0, done.stderr
    said = json.loads(done.stdout)
    assert said["agent"] == "claude" and "cwd-workspace" in said["plugins"]
    assert said["live"] == [f"{sb.home}/.local/state/claude-sandbox/dev-server/items.json"]
    assert said["lists"] == [] and "checkout" not in said  # agent-workspace is off in BASE
    assert done.calls == []


def test_a_task_reaches_the_agent_as_agent_task(sb, run_sh):
    done = run_sh("--run-id", "0a1b2c", "--task", "Fix #7: it's \"broken\"", CLAUDE_CODE_OAUTH_TOKEN="t")
    [run] = calls(done, "run")
    assert "AGENT_TASK=Fix #7: it's \"broken\"" in run
    run = calls(run_sh("--run-id", "0a1b2c", CLAUDE_CODE_OAUTH_TOKEN="t"), "run")[-1]  # the log is shared
    assert not any(arg.startswith("AGENT_TASK=") for arg in run)  # no task, no variable


def test_set_is_a_setting_of_this_run_alone_over_the_projects_own(sb, run_sh):
    """--set: what a plugin's web_start starts a run with, and SANDBOX_STARTED_BY only that way."""
    project = {**BASE, "env": {**BASE["env"], "CLAUDE_EFFORT": "high"}}
    seen = sb.tmp / "by"
    sb.stub("docker", f'[ "$1" != run ] || {{ printf "%s\\n" "$@" | grep EFFORT; echo "${{SANDBOX_STARTED_BY-unset}}"; }} >"{seen}"\n')
    assert run_sh("--set", "CLAUDE_EFFORT=low", "--set", "SANDBOX_STARTED_BY=pr-review", config=project,
                  CLAUDE_CODE_OAUTH_TOKEN="t").returncode == 0
    assert seen.read_text() == "CLAUDE_EFFORT=low\npr-review\n"
    assert run_sh(config=project, CLAUDE_CODE_OAUTH_TOKEN="t", SANDBOX_STARTED_BY="someone").returncode == 0
    assert seen.read_text() == "CLAUDE_EFFORT=high\nunset\n"  # not from your shell


def test_a_chat_runs_without_a_terminal_behind_the_agents_bridge(sb, run_sh):
    """--chat (what the web UI starts): stdin stays open and no pty is allocated, since the
    container's stdio is the chat bridge's wire; the launch stage reads AGENT_UI."""
    run = calls(run_sh("--resume", "0a1b2c", "--chat", CLAUDE_CODE_OAUTH_TOKEN="t"), "run")[-1]
    assert run[:5] == ["run", "-i", "-e", "AGENT_UI=chat", "--rm"] and "-it" not in run
    assert "RESUME=1" in run
    run = calls(run_sh("--run-id", "0a1b2c", CLAUDE_CODE_OAUTH_TOKEN="t"), "run")[-1]
    assert run[:3] == ["run", "-it", "--rm"] and "AGENT_UI=chat" not in run


def test_a_plugin_refusing_stops_the_run_before_docker(run_sh):
    done = run_sh()  # no CLAUDE_CODE_OAUTH_TOKEN: the agent's host.sh dies
    assert done.returncode == 1 and done.calls == []
    assert "Claude Code needs credentials: set CLAUDE_AUTH" in done.stderr and "Traceback" not in done.stderr
    # A token is not a setting a project makes: it only names one.
    done = run_sh(config={**BASE, "env": {**BASE["env"], "CLAUDE_CODE_OAUTH_TOKEN": "t"}})
    assert ".env.CLAUDE_CODE_OAUTH_TOKEN is not a sandbox setting" in done.stderr


def test_what_a_host_stage_exports_reaches_docker(sb, run_sh):
    """herdr's host.sh exports HERDR_AGENT for the docker client itself, as it did when host.sh was
    sourced into run.sh."""
    seen = sb.tmp / "herdr"
    sb.stub("docker", f'[ "$1" != run ] || echo "${{HERDR_AGENT-unset}}" >"{seen}"\n')
    assert run_sh(CLAUDE_CODE_OAUTH_TOKEN="t", HERDR_ENV="1").returncode == 0
    assert seen.read_text() == "claude\n"


def test_the_container_exit_status_is_the_runs(sb, run_sh):
    sb.stub("docker", '[ "$1" != run ] || exit 3\n')
    assert run_sh(CLAUDE_CODE_OAUTH_TOKEN="t").returncode == 3
    sb.stub("docker", '[ "$1" != build ] || exit 5\n')
    assert run_sh(CLAUDE_CODE_OAUTH_TOKEN="t").returncode == 5


def test_a_hangup_cleans_up_and_leaves_the_docker_client_be(sb, run_sh, short_tmp):
    """The web UI stops a session with a SIGHUP to its process group: the stage's exit hooks run
    (upstream-proxy's proxy stops), while `docker run` is left to the `docker rm` that follows."""
    started = sb.tmp / "started"
    sb.stub("docker", f'[ "$1" != run ] || {{ trap "" HUP; echo $$ >"{started}"; sleep 30; }}\n')
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    config = json.loads(json.dumps(BASE))  # upstream-proxy: a proxy on this machine, stopped by an exit hook
    config["plugins"]["upstream-proxy"] = {"routes": [{"name": "api", "port": port, "upstream": "http://127.0.0.1:9"}]}
    sb.config(config)
    env = sb._env({"CLAUDE_CODE_OAUTH_TOKEN": "t", "TMPDIR": str(short_tmp)})
    # Files, not pipes: the docker client, left running, would hold a pipe open past run.sh.
    out, err = open(sb.tmp / "out", "w"), open(sb.tmp / "err", "w")
    proc = subprocess.Popen([REPO / "run.sh", "--run-id", "0a1b2c", "--chat"], cwd=sb.cwd, env=env,
                            stdin=subprocess.PIPE, stdout=out, stderr=err, start_new_session=True)
    try:
        for _ in range(300):
            if started.exists() and started.read_text().strip():
                break
            time.sleep(0.1)
        else:
            raise AssertionError((sb.tmp / "err").read_text())
        [proxy_dir] = glob.glob(f"{short_tmp}/upstream-proxy-*")
        assert "proxy.pid" in os.listdir(proxy_dir)
        os.killpg(proc.pid, signal.SIGHUP)
        assert proc.wait(timeout=30) == 128 + signal.SIGHUP, (sb.tmp / "err").read_text()
        assert os.listdir(proxy_dir) == ["lock"]  # the stage's exit hook stopped upstream-proxy's
        os.kill(int(started.read_text()), 0)  # the docker client is still there
    finally:
        if started.exists() and started.read_text().strip():
            try:
                os.kill(int(started.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
        out.close()
        err.close()


def test_a_web_action_needs_its_plugin_enabled(run_sh):
    done = run_sh("--web-action", "github-auth", "close-pr", "3")  # github-auth is off in BASE
    assert done.returncode == 1 and done.stdout == ""
    assert "Plugin 'github-auth' is not enabled for this project." in done.stderr


def test_project_names_its_file_and_the_repo_it_works_on(sb, run_sh):
    """`--project NAME`: ~/.config/claude-sandbox/projects/NAME.json is its config, and its repo,
    not the directory run.sh was started in, is the one the agent works on."""
    listing = sb.home / ".config/claude-sandbox/projects"
    listing.mkdir(parents=True)
    repo = sb.tmp / "repo"
    repo.mkdir()
    (listing / "app.json").write_text(json.dumps({"repo": str(repo), **BASE}))
    done = run_sh("--project", "app", config=None, CLAUDE_CODE_OAUTH_TOKEN="t")
    assert done.returncode == 0, done.stderr
    [run] = calls(done, "run")
    assert f"{repo}:/workspace" in run and f"📄 Project config: {listing / 'app.json'}" in done.stdout
    for name, message in (("nope", "No project 'nope'"), ("../app", "is not a project name")):
        done = run_sh("--project", name, config=None)
        assert done.returncode and message in done.stderr
    (listing / "app.json").write_text(json.dumps(BASE))
    done = run_sh("--project", "app", config=None)
    assert done.returncode and "names no repo" in done.stderr


def test_a_projects_repo_may_be_a_git_url_never_cloned_on_this_machine(sb, run_sh):
    """A URL repo (private ones too) is cloned only in the container: HOST_CWD is empty, REPO_URL
    the URL, and the plugins that need a checkout here refuse it."""
    listing = sb.home / ".config/claude-sandbox/projects"
    listing.mkdir(parents=True)
    url = "https://github.com/acme/private-widgets.git"  # unreachable: nothing may fetch it
    plugins = {**BASE["plugins"], "cwd-workspace": {"enabled": False}, "agent-workspace": {"enabled": True},
               "branch-guard": {"enabled": False}}
    (listing / "app.json").write_text(json.dumps({**BASE, "repo": url, "plugins": plugins}))
    done = run_sh("--project", "app", config=None, CLAUDE_CODE_OAUTH_TOKEN="t", GIT_TERMINAL_PROMPT="0")
    assert done.returncode == 0, done.stderr
    assert any("/private-widgets-" in a and a.endswith(":/workspace") for a in calls(done, "run")[0])
    assert not (sb.home / ".cache/claude-sandbox/repos").exists()
    (listing / "app.json").write_text(json.dumps({**BASE, "repo": url}))  # cwd-workspace on
    done = run_sh("--project", "app", config=None, CLAUDE_CODE_OAUTH_TOKEN="t")
    assert done.returncode and "no checkout on this machine to mount" in done.stderr
