#!/usr/bin/env python3
"""The ports plugin on the host: a run's share of the central port proxy.

Usage: lease.py join RUN_ID PID    joins (or starts) the proxy; prints the `docker run` arguments, one a line
       lease.py leave RUN_ID PID   leaves it; the last run out stops it
       lease.py items              the proxy's items file, for web_live_items

Every sandbox has a network namespace of its own, so two sessions can both serve on :3000. Which
ports a sandbox opens is the project's choice: $PORTS lists them, and nothing else is published
(nor shown on the dashboard): users/<pid> holds them, and the proxy reads them from there. Inside, a
helper of the agent's (../bin/publish-ports.py, started by the plugin's agent-init.sh) offers each of those a process of the agent's listens on as a unix socket in a
directory mounted from here; one central proxy on this machine (portd.py), shared by every
sandbox of every project, gives each a port on its bind address — the same number while it is free,
another free one otherwise. The first run starts the proxy; it exits by itself once no run using
it is alive. PID is the process that stands for the run while it lives (the host stage's shell).

The bind address is $PORTS_BIND, else the address the web UI listens on ($SANDBOX_WEB_BIND, which
src/server/server.py exports for every run it starts: a port button then works from wherever the
page was opened), else 127.0.0.1. Only the web UI's address keeps the name it was given
($SANDBOX_WEB_NAME) for the links.

    ${TMPDIR:-/tmp}/sandbox-ports-<uid>-<bind>/
      lock            taken to join or leave, and by the proxy before it exits
      users/<pid>     one per run using the proxy, holding its RUN_ID and its PORTS
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
import sys
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent


class Die(Exception):
    """A refusal, said as `❌ <message>`: it stops the run."""


def say(line: str) -> None:
    print(line, file=sys.stderr, flush=True)  # stdout carries the docker arguments


def bind_of(env: dict) -> str:
    return env.get("PORTS_BIND") or env.get("SANDBOX_WEB_BIND") or "127.0.0.1"


def settings(env: dict) -> tuple[str, list[str]]:
    """The bind address and PORTS, checked: an address, and port numbers."""
    bind = bind_of(env)
    if not re.fullmatch(r"[0-9A-Fa-f.:]+", bind):
        raise Die(f"PORTS_BIND must be an IP address (got: {bind})")
    ports = (env.get("PORTS") or "").split()
    for port in ports:
        if not re.fullmatch(r"[1-9][0-9]{0,4}", port) or int(port) > 65535:
            raise Die(f"PORTS must list port numbers, space-separated (got: {env.get('PORTS')})")
    return bind, ports


def ports_dir(env: dict) -> Path:
    """The central proxy's directory, for this user and bind address."""
    bind = bind_of(env).replace(":", "_")
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
                if f.read_text().split()[:1] == [run_id]:
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
        directory — only when the project configured ports to publish ($PORTS). The directory is the
        agent's to write: the proxy follows nothing planted there and publishes only these ports
        (portd.py). The `docker run` arguments."""
        bind, ports = settings(self.env)
        if not ports:
            say('🔌 Ports: none published (list them in PORTS, e.g. PORTS="3000 5173")')
            return []
        self.dir.mkdir(parents=True, exist_ok=True)
        st = os.lstat(self.dir)
        if stat.S_ISLNK(st.st_mode) or st.st_uid != os.getuid():
            raise Die(f"'{self.dir}' is not yours; remove it and run again.")
        for d in (self.dir, self.dir / "users", self.dir / "runs"):
            d.mkdir(exist_ok=True)
            d.chmod(0o700)
        with self._locked():
            # The ports with it: the proxy publishes those alone, whatever the container offers.
            (self.dir / "users" / self.pid).write_text(f"{self.run_id} {' '.join(ports)}\n")
            self.joined = True
            self._prune()
            run = self.dir / "runs" / self.run_id
            run.mkdir(exist_ok=True)
            # The agent's to write, whichever uid it has in there (rootless docker keeps it apart
            # from yours); the 0700 directories above keep everyone else on this machine out.
            run.chmod(0o777)
            try:
                pid = (self.dir / "portd.pid").read_text().strip()
            except OSError:
                pid = ""
            if not pid or not _alive(pid):
                with open(self.dir / "portd.log", "a") as log:
                    # The name the web UI's address was resolved from (its --bind), for the links; only a host name.
                    name = self.env.get("SANDBOX_WEB_NAME") or ""
                    name = name if bind == self.env.get("SANDBOX_WEB_BIND") else ""
                    name = name if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", name) else ""
                    proxy = subprocess.Popen([str(HERE / "portd.py"), "--bind", bind,
                                              "--name", name, str(self.dir)],
                                             stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
                (self.dir / "portd.pid").write_text(f"{proxy.pid}\n")
        say(f"🔌 Ports: {', '.join(ports)} published on {bind}")
        return ["-v", f"{run}:/run/ports/sockets", "-e", f"PORTS_BIND={bind}", "-e", f"PORTS={' '.join(ports)}"]

    def release(self):
        """Leaves the proxy; the last run out stops it rather than wait for it to notice."""
        if not self.joined and not (self.dir / "users" / self.pid).exists():
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


def main(argv: list[str]) -> int:
    try:
        if argv[:1] == ["items"] and len(argv) == 1:
            print(items_file(os.environ))
        elif argv[:1] in (["join"], ["leave"]) and len(argv) == 3:
            lease = Ports(dict(os.environ), argv[1], int(argv[2]))
            if argv[0] == "leave":
                lease.release()
            else:
                print("\n".join(lease.start()))
        else:
            print(__doc__.split("\n\n")[1], file=sys.stderr)
            return 2
    except Die as e:
        print(f"❌ {e}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
