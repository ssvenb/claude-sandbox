"""Shared harness: run the host-side bash libraries, plugin stages and Python helpers in isolation.

Host stages are sourced into a fresh `bash` with run.sh's libraries loaded and `set -euo
pipefail`, exactly as run.sh sources them; the `docker run`/`docker build` arguments they
contribute are read back afterwards. Container stages are sourced into `sh` the same way
agent-setup.sh does, with the frameworks pointed at this checkout instead of /opt.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# The root helpers import peer_owner from /usr/local/lib/sandbox (where the image installs it);
# importing it here first makes them use this checkout's copy.
sys.path.insert(0, str(REPO / "src/lib"))
import peer_owner  # noqa: E402,F401

HOST_LIBS = "\n".join(f". src/lib/{lib}.sh" for lib in (
    "host-plugins", "host-credentials", "host-agents",
    "host-project-config", "host-project-env", "host-settings"))


def load(rel: str):
    """Import a script that is not a package module (dashes in its name, no .py import path)."""
    path = REPO / rel
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@dataclass
class Run:
    code: int
    out: str
    err: str
    args: list[str] = field(default_factory=list)        # DOCKER_ARGS
    build_args: list[str] = field(default_factory=list)  # BUILD_ARGS
    prompt: str = ""                                     # AGENT_PROMPT_FILE, container stages

    @property
    def env(self) -> dict[str, str]:
        """The `-e NAME=VALUE` pairs among the docker args."""
        pairs = [self.args[i + 1] for i, a in enumerate(self.args) if a == "-e"]
        return dict(p.split("=", 1) for p in pairs)

    @property
    def mounts(self) -> list[str]:
        return [self.args[i + 1] for i, a in enumerate(self.args) if a == "-v"]

    @property
    def builds(self) -> dict[str, str]:
        pairs = [self.build_args[i + 1] for i, a in enumerate(self.build_args) if a == "--build-arg"]
        return dict(p.split("=", 1) for p in pairs)

    def ok(self) -> "Run":
        assert self.code == 0, f"exit {self.code}\nstdout:\n{self.out}\nstderr:\n{self.err}"
        return self

    def dies(self, message: str) -> "Run":
        assert self.code != 0, f"expected a failure, got exit 0\nstdout:\n{self.out}"
        assert message in self.err, f"{message!r} not in stderr:\n{self.err}"
        return self


def _nul_list(path: Path) -> list[str]:
    if not path.exists():
        return []
    data = path.read_text()
    return data.split("\0")[:-1] if data else []


class Sandbox:
    """A throwaway project checkout, home directory and stub bin dir for one test."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.cwd = tmp / "project"
        self.home = tmp / "home"
        self.bin = tmp / "bin"
        for d in (self.cwd, self.home, self.bin):
            d.mkdir()
        self.env = {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "HOME": str(self.home),
            "LANG": "C.UTF-8",
            "HOST_CWD": str(self.cwd),
            "RUN_ID": "abc123",
            "RUN_DATE": "20260102",
            "RESUME": "0",
            "AGENT": "claude",
        }

    def config(self, data: dict) -> Path:
        path = self.cwd / ".claude-sandbox.json"
        path.write_text(json.dumps(data))
        return path

    def dotenv(self, text: str) -> Path:
        path = self.cwd / ".env"
        path.write_text(text)
        return path

    def stub(self, name: str, body: str) -> Path:
        """An executable on PATH ahead of the real one; body is a sh script."""
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)
        return path

    def _env(self, env: dict) -> dict:
        merged = {**self.env, **env}
        return {k: str(v) for k, v in merged.items() if v is not None}

    def bash(self, snippet: str, timeout: float = 30, **env) -> Run:
        """Source run.sh's libraries, then run snippet; read back DOCKER_ARGS and BUILD_ARGS."""
        dump = self.tmp / "dump"
        script = f"""set -euo pipefail
cd "{REPO}"
{HOST_LIBS}
{snippet}
{{ [ ${{#DOCKER_ARGS[@]}} -eq 0 ] || printf '%s\\0' "${{DOCKER_ARGS[@]}}"; }} >"{dump}.docker"
{{ [ ${{#BUILD_ARGS[@]}} -eq 0 ] || printf '%s\\0' "${{BUILD_ARGS[@]}}"; }} >"{dump}.build"
"""
        for suffix in (".docker", ".build"):
            Path(f"{dump}{suffix}").unlink(missing_ok=True)
        done = subprocess.run(["bash", "-c", script], env=self._env(env), capture_output=True,
                              text=True, timeout=timeout)
        return Run(done.returncode, done.stdout, done.stderr,
                   _nul_list(Path(f"{dump}.docker")), _nul_list(Path(f"{dump}.build")))

    def plugin(self, name: str, **env) -> Run:
        """One plugin's host stage, after the project's config and .env were loaded."""
        return self.bash(f"project_config_load\nproject_env_load\nENABLED_PLUGINS={name}\n"
                         "plugins_host_stage", **env)

    def agent(self, **env) -> Run:
        return self.bash("agent_resolve\nagent_host_stage", **env)

    def sh(self, snippet: str, **env) -> Run:
        """A container stage: sourced by `sh` with the container frameworks, as agent-setup.sh does."""
        prompt = self.tmp / "prompt"
        prompt.write_text("")
        script = f"""set -e
. "{REPO}/src/lib/plugins.sh"
. "{REPO}/src/lib/agents.sh"
{snippet}
"""
        base = {"PLUGIN_ROOT": REPO / "plugins", "AGENT_ROOT": REPO / "agents",
                "AGENT_PROMPT_FILE": prompt}
        done = subprocess.run(["sh", "-c", script], env=self._env({**base, **env}),
                              capture_output=True, text=True, timeout=30,
                              start_new_session=True)
        return Run(done.returncode, done.stdout, done.stderr, prompt=prompt.read_text())


@pytest.fixture
def sb(tmp_path) -> Sandbox:
    return Sandbox(tmp_path)


@pytest.fixture
def short_tmp():
    """A directory with a short path: AF_UNIX socket paths are capped near 108 bytes."""
    path = Path(tempfile.mkdtemp(prefix="sbt-", dir="/tmp"))
    yield path
    shutil.rmtree(path, ignore_errors=True)
