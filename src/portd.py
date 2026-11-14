#!/usr/bin/env python3
"""The central port proxy: publishes every running sandbox's servers on this machine.

Runs on the HOST, one per user (and bind address), shared by every sandbox of every project: the
first run.sh starts it, and it exits once no run.sh that uses it is alive.

Usage: portd.py [--bind ADDR] <dir>

Each sandbox has a network namespace of its own, so two of them can both serve on :3000. Inside,
a root helper (src/publish-ports.py) watches what the agent listens on and offers each port as a unix
socket, <dir>/runs/<RUN_ID>/<port>.sock, in a directory bind-mounted from here. This process
gives each such socket a TCP port on this machine — the same number while it is free, any free
one otherwise — and relays connections to it. Ports are handed out per session: a run keeps the
host port a server of its got for as long as this process lives, across restarts of that server.

<dir>/users/<pid> files name the run.sh processes using it, each holding its RUN_ID: a run
directory with no live run.sh claiming it is ignored (its container is gone), and with no live
user at all this process cleans up and exits — taking <dir>/lock first, so a run.sh starting
right then either sees it gone or is seen by it.

What is published is written to <dir>/ports.json, and as the web UI's session items to
<dir>/items.json (see `web_live_items` in src/lib/host-plugins.sh, `items_file` in src/host/ports.py).
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import signal
import socket
import stat
import sys
import threading
import time

RUN_ID = re.compile(r"[0-9a-f]{6}")
SOCK = re.compile(r"([1-9][0-9]{0,4})\.sock")
SCAN = 0.5  # seconds between looks at the run directories
GRACE = 10  # seconds a fresh daemon waits for its first user before giving up


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def pump(src: socket.socket, dst: socket.socket) -> None:
    try:
        while data := src.recv(65536):
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def relay(client: socket.socket, path: str) -> None:
    up = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        up.connect(path)
    except OSError as e:
        log(f"{path}: {e}")
        up.close()
        client.close()
        return
    other = threading.Thread(target=pump, args=(up, client), daemon=True)
    other.start()
    pump(client, up)
    other.join()
    client.close()
    up.close()


class Published:
    """One sandbox port, listening on a host port of its own."""

    def __init__(self, run_id: str, port: int, path: str, listener: socket.socket):
        self.run_id, self.port, self.path, self.listener = run_id, port, path, listener
        self.host_port = listener.getsockname()[1]
        self.closed = False
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self) -> None:
        while not self.closed:
            try:
                client, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                if self.closed:
                    break
                time.sleep(0.1)
                continue
            client.settimeout(None)
            threading.Thread(target=relay, args=(client, self.path), daemon=True).start()

    def close(self) -> None:
        self.closed = True
        # shutdown first: a plain close leaves a thread blocked in accept() holding the port.
        for stop in (lambda: self.listener.shutdown(socket.SHUT_RDWR), self.listener.close):
            try:
                stop()
            except OSError:
                pass


def listen(bind: str, port: int) -> socket.socket:
    family = socket.AF_INET6 if ":" in bind else socket.AF_INET
    s = socket.socket(family, socket.SOCK_STREAM)
    try:
        # Past TIME_WAIT leftovers only; on Linux it never lets a second listener share the port.
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((bind, port))
        s.listen(128)
        s.settimeout(1)  # so close() is noticed by the accepting thread
        return s
    except OSError:
        s.close()
        raise


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # someone else's process now: not ours any more
        return False
    return True


def claims(users_dir: str) -> dict[str, str]:
    """RUN_ID → pid of a live run.sh using this daemon for it."""
    found = {}
    try:
        entries = os.listdir(users_dir)
    except OSError:
        return found
    for entry in entries:
        if not entry.isdigit() or not alive(int(entry)):
            continue
        try:
            with open(os.path.join(users_dir, entry), encoding="utf-8") as fh:
                run_id = fh.read().strip()
        except OSError:
            continue
        if RUN_ID.fullmatch(run_id):
            found[run_id] = entry
    return found


def offered(runs_dir: str, live: dict[str, str]) -> dict[tuple[str, int], str]:
    """(RUN_ID, port) → socket path, for every port a live run offers. Only real sockets: what
    the container put there is followed nowhere else (no symlinks, no other file types)."""
    found = {}
    for run_id in live:
        d = os.path.join(runs_dir, run_id)
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for name in names:
            m = SOCK.fullmatch(name)
            path = os.path.join(d, name)
            try:
                if not m or not stat.S_ISSOCK(os.lstat(path).st_mode) or int(m[1]) > 65535:
                    continue
            except OSError:
                continue
            found[(run_id, int(m[1]))] = path
    return found


def url_host(bind: str) -> str:
    """How the page should name this machine in a link: by whatever name the page itself was
    opened by ({host}, filled in by the page) — on every interface that reaches the port, and on
    loopback the page is on this machine too — or, bound to one address, by that address."""
    if bind in ("0.0.0.0", "::", "127.0.0.1", "::1"):
        return "{host}"
    return f"[{bind}]" if ":" in bind else bind


def write(path: str, data) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    os.replace(tmp, path)


class Daemon:
    def __init__(self, base: str, bind: str):
        self.base, self.bind = base, bind
        self.runs, self.users = os.path.join(base, "runs"), os.path.join(base, "users")
        self.published: dict[tuple[str, int], Published] = {}
        self.assigned: dict[tuple[str, int], int] = {}  # host port a run's port had, to get it again
        self.said = None

    def publish(self, key: tuple[str, int], path: str) -> None:
        run_id, port = key
        # The port it had before, then the same number, then whatever is free.
        for want in dict.fromkeys(p for p in (self.assigned.get(key), port, 0) if p is not None):
            if 0 < want < 1024:
                continue
            try:
                lsock = listen(self.bind, want)
            except OSError:
                continue
            p = self.published[key] = Published(run_id, port, path, lsock)
            self.assigned[key] = p.host_port
            log(f"{run_id}:{port} → {self.bind}:{p.host_port}")
            return
        log(f"{run_id}:{port}: no host port to listen on")

    def scan(self) -> bool:
        """One look at the run directories. False once nobody uses this daemon any more."""
        live = claims(self.users)
        found = offered(self.runs, live)
        for key in [k for k in self.published if k not in found or self.published[k].path != found[k]]:
            self.published.pop(key).close()
            log(f"{key[0]}:{key[1]} withdrawn")
        for key, path in found.items():
            if key not in self.published:
                self.publish(key, path)
        for key in [k for k in self.assigned if k[0] not in live]:
            del self.assigned[key]  # the run is over: its next session may get any port
        self.report()
        return bool(live)

    def report(self) -> None:
        ports = sorted(({"run_id": p.run_id, "port": p.port, "host_port": p.host_port}
                        for p in self.published.values()), key=lambda p: (p["run_id"], p["port"]))
        if ports == self.said:
            return
        host = url_host(self.bind)
        items = [{"run_id": p["run_id"], "ref": f":{p['port']}", "url": f"http://{host}:{p['host_port']}/",
                  "title": f"Port {p['port']} of the sandbox, published on {self.bind}:{p['host_port']}"}
                 for p in ports]
        write(os.path.join(self.base, "ports.json"), ports)
        write(os.path.join(self.base, "items.json"), items)
        self.said = ports

    def done(self) -> bool:
        """Under the lock run.sh takes to join: exit only if still nobody joined."""
        with open(os.path.join(self.base, "lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if claims(self.users):
                return False
            self.stop()
            return True

    def stop(self) -> None:
        for p in self.published.values():
            p.close()
        self.published.clear()
        for name in ("ports.json", "items.json", "portd.pid"):
            try:
                os.unlink(os.path.join(self.base, name))
            except OSError:
                pass

    def run(self) -> None:
        started = time.monotonic()
        while True:
            if not self.scan() and time.monotonic() - started > GRACE and self.done():
                log("nobody uses the ports any more: exiting")
                return
            time.sleep(SCAN)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bind", default="127.0.0.1", help="address published ports listen on")
    ap.add_argument("dir")
    args = ap.parse_args()
    # Every sandbox uses this one process, so it must not die with the terminal of the run that
    # happened to start it (a SIGHUP to that run's process group).
    try:
        os.setsid()
    except OSError:
        pass
    daemon = Daemon(args.dir, args.bind)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        daemon.run()
    except (KeyboardInterrupt, SystemExit):
        daemon.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
