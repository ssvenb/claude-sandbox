"""The plugins' own host stages, which stay shell: one bash process (src/lib/host-stage.sh) sources
each enabled plugin's host.sh and then the agent's — or, for the web UI, their web.sh — with the
helpers of src/lib/host-*.sh, exactly as run.sh used to source them into itself.

For a run, that bash outlives the stage: what the plugins registered with `on_exit` (and the
credentials refresher, and any proxy a plugin started) must last as long as the container does.
It reports what the stage produced (the `docker run` and `docker build` arguments, and its
environment, which a host.sh may have exported into) in files, says so on a pipe, then waits on
its stdin; closing
that — finish(), or this process dying for any reason — lets it run the exit hooks and go.
"""
from __future__ import annotations

import json
import os
import select
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import SANDBOX, Die

SCRIPT = SANDBOX / "src/lib/host-stage.sh"
# What bash itself puts in its environment, not anything a plugin exported.
SHELL_NOISE = {"_", "SHLVL", "PWD", "OLDPWD"}


@dataclass
class Report:
    docker: list = field(default_factory=list)  # DOCKER_ARGS
    build: list = field(default_factory=list)   # BUILD_ARGS
    env: dict = field(default_factory=dict)     # its exported environment, for docker build and run
    web: dict | None = None                     # WEB_JSON, from a web stage


def environ(env: dict, *, config, agent_dir, enabled, resume) -> dict:
    """The stage's environment: everything resolved so far, for the host.sh scripts to read. The
    ones run.sh never exported are unexported again by the stage (host-stage.sh)."""
    return {**env, "PROJECT_CONFIG_JSON": json.dumps(config, separators=(",", ":")) if config is not None else "",
            "AGENT_DIR": str(agent_dir), "ENABLED_PLUGINS": " ".join(enabled), "RESUME": resume}


def _read_report(proc: subprocess.Popen, fd: int) -> bytes:
    """The stage's one line ("done"), or what there is once it exits without one. Not read to EOF:
    what the stage left running (a proxy, the credentials refresher) holds the pipe open too."""
    data = b""
    while not data.endswith(b"\n"):
        ready, _, _ = select.select([fd], [], [], 0.2)
        if ready:
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                break
            data += chunk
        elif proc.poll() is not None:
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:
                break
    return data


def _nul_list(report: str, name: str) -> list[str]:
    data = Path(report, name).read_bytes().decode("utf-8", "surrogateescape")
    return data.split("\0")[:-1] if data else []


class Stage:
    """One bash running one of host-stage.sh's modes: `host`, `web` or `web-action`."""

    def __init__(self, mode: str, env: dict, *args: str, stdout=None):
        with tempfile.TemporaryDirectory(prefix="sandbox-stage-") as report:
            r, w = os.pipe()
            try:
                self.proc = subprocess.Popen(["bash", str(SCRIPT), mode, *args], cwd=SANDBOX,
                                             env={**env, "SANDBOX_STAGE_REPORT_FD": str(w),
                                                  "SANDBOX_STAGE_REPORT": report},
                                             pass_fds=(w,), stdin=subprocess.PIPE, stdout=stdout)
            finally:
                os.close(w)
            try:
                done = _read_report(self.proc, r)
            finally:
                os.close(r)
            if done != b"done\n":
                self.proc.stdin.close()
                raise StageFailed(self.proc.wait() or 1)
            self.report = Report()
            if mode == "web":
                self.report.web = json.loads(Path(report, "web.json").read_text())
            elif mode == "host":
                self.report.docker, self.report.build = _nul_list(report, "docker"), _nul_list(report, "build")
                pairs = (item.split("=", 1) for item in _nul_list(report, "env") if "=" in item)
                self.report.env = {k: v for k, v in pairs if k not in SHELL_NOISE}

    def finish(self) -> int:
        """Lets the stage go: its exit hooks run, its refresher stops. Its exit status."""
        if self.proc.stdin and not self.proc.stdin.closed:
            try:
                self.proc.stdin.close()
            except BrokenPipeError:
                pass
        return self.proc.wait()


class StageFailed(Die):
    """The stage refused (a plugin's `die`, which already said why) with this exit status."""

    def __init__(self, code: int):
        super().__init__("")
        self.code = code
