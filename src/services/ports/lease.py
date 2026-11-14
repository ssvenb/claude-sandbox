"""Published ports.

Every sandbox has a network namespace of its own, so two sessions can both serve on :3000. Which
ports a sandbox opens is the project's choice: $PORTS lists them, and nothing else is published
(nor shown on the dashboard). Inside, a root helper (src/services/ports/publish-ports.py, started by
entrypoint.sh) offers each of those a process of the agent's listens on as a unix socket in a
directory mounted from here; one central proxy on this machine (src/services/ports/portd.py), shared by every
sandbox of every project, gives each a port on $PORTS_BIND — the same number while it is free,
another free one otherwise. The first run starts the proxy; it exits by itself once no run using
it is alive.

    ${TMPDIR:-/tmp}/sandbox-ports-<uid>-<bind>/
      lock            taken to join or leave, and by the proxy before it exits
      users/<pid>     one per run.sh using the proxy, holding its RUN_ID
      runs/<RUN_ID>/  the run's sockets, mounted at /run/ports/sockets
      portd.pid, portd.log, ports.json, items.json (the web UI's session buttons)
"""
from __future__ import annotations

import fcntl
import os
import re
import shutil
import signal
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path

from orchestrator import SANDBOX, Die, say

ADD_HOST = "--add-host=host.docker.internal:host-gateway"


def settings(env: dict) -> tuple[str, list[str]]:
    """PORTS_BIND and PORTS, checked: an address, and port numbers."""
    bind = env.get("PORTS_BIND") or "127.0.0.1"
    if not re.fullmatch(r"[0-9A-Fa-f.:]+", bind):
        raise Die(f"PORTS_BIND must be an IP address (got: {bind})")
    ports = (env.get("PORTS") or "").split()
    for port in ports:
        if not re.fullmatch(r"[1-9][0-9]{0,4}", port) or int(port) > 65535:
            raise Die(f"PORTS must list port numbers, space-separated (got: {env.get('PORTS')})")
    return bind, ports


def ports_dir(env: dict) -> Path:
    """The central proxy's directory, for this user and $PORTS_BIND."""
    bind = (env.get("PORTS_BIND") or "127.0.0.1").replace(":", "_")
    return Path(f"{env.get('TMPDIR') or '/tmp'}/sandbox-ports-{os.getuid()}-{bind}")


def items_file(env: dict) -> str:
    """The proxy's list of published ports: the web UI's live session buttons (web_live_items)."""
    return str(ports_dir(env) / "items.json")


def _alive(name: str) -> bool:
    try:
        os.kill(int(name), 0)
        return True
    except (ValueError, OSError):
        return False


class Ports:
    """This run's share of the central proxy: joined by start(), left by release()."""

    def __init__(self, env: dict, run_id: str, pid: int | None = None):
        self.env, self.run_id, self.pid = env, run_id, str(pid or os.getpid())
        self.dir = ports_dir(env)
        self.joined = False

    @contextmanager
    def _locked(self):
        with open(self.dir / "lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def _users(self):
        return [f for f in (self.dir / "users").iterdir()] if (self.dir / "users").is_dir() else []

    def _claimed(self, run_id: str) -> bool:
        """Whether a live run.sh other than this one uses that run's directory."""
        for f in self._users():
            if f.name == self.pid or not _alive(f.name):
                continue
            try:
                if f.read_text().strip() == run_id:
                    return True
            except OSError:
                pass
        return False

    def _prune(self):
        """Forget the runs whose run.sh died before it could leave, and their directories."""
        for f in self._users():
            if not _alive(f.name):
                f.unlink(missing_ok=True)
        try:
            mine = (self.dir / "users" / self.pid).read_text().strip()
        except OSError:
            mine = None
        runs = self.dir / "runs"
        for d in (runs.iterdir() if runs.is_dir() else []):
            if d.is_dir() and not self._claimed(d.name) and d.name != mine:
                shutil.rmtree(d, ignore_errors=True)

    def start(self) -> list[str]:
        """Joins (or starts) the central proxy for this run, and hands the container its socket
        directory — only when the project configured ports to publish ($PORTS). Its sockets sit
        under a root-only directory in the container (entrypoint.sh), so the agent cannot plant
        anything there for this machine to connect to. The `docker run` arguments."""
        bind, ports = settings(self.env)
        args = [ADD_HOST]
        if not ports:
            say('🔌 Ports: none published (list them in PORTS, e.g. PORTS="3000 5173")')
            return args
        self.dir.mkdir(parents=True, exist_ok=True)
        st = os.lstat(self.dir)
        if stat.S_ISLNK(st.st_mode) or st.st_uid != os.getuid():
            raise Die(f"'{self.dir}' is not yours; remove it and run again.")
        for d in (self.dir, self.dir / "users", self.dir / "runs"):
            d.mkdir(exist_ok=True)
            d.chmod(0o700)
        with self._locked():
            (self.dir / "users" / self.pid).write_text(f"{self.run_id}\n")
            self.joined = True
            self._prune()
            run = self.dir / "runs" / self.run_id
            run.mkdir(exist_ok=True)
            run.chmod(0o755)
            try:
                pid = (self.dir / "portd.pid").read_text().strip()
            except OSError:
                pid = ""
            if not pid or not _alive(pid):
                with open(self.dir / "portd.log", "a") as log:
                    proxy = subprocess.Popen([str(SANDBOX / "src/services/ports/portd.py"), "--bind", bind, str(self.dir)],
                                             stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
                (self.dir / "portd.pid").write_text(f"{proxy.pid}\n")
        say(f"🔌 Ports: {', '.join(ports)} published on {bind}")
        return args + ["-v", f"{run}:/run/ports/sockets", "-e", f"PORTS_BIND={bind}", "-e", f"PORTS={' '.join(ports)}"]

    def release(self):
        """Leaves the proxy; the last run out stops it rather than wait for it to notice."""
        if not self.joined:
            return
        self.joined = False
        with self._locked():
            (self.dir / "users" / self.pid).unlink(missing_ok=True)
            if not self._claimed(self.run_id):
                shutil.rmtree(self.dir / "runs" / self.run_id, ignore_errors=True)
            self._prune()
            if not self._users():
                try:
                    os.kill(int((self.dir / "portd.pid").read_text().strip()), signal.SIGTERM)
                except (OSError, ValueError):
                    pass
                for name in ("portd.pid", "ports.json", "items.json"):
                    (self.dir / name).unlink(missing_ok=True)
