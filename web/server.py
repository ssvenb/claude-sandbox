#!/usr/bin/env python3
"""Web UI to orchestrate sandboxes: one page listing the configured projects, their running
sessions and open pull requests, with a terminal for each session.

Runs on the HOST, as you, next to run.sh — a session is `run.sh` in a pty with the project as its
cwd, exactly what you would type yourself. Standard library only; the page loads xterm.js from a
CDN. Terminal output goes out as server-sent events, keystrokes come back as POSTs.

    web/server.py [--port 8787] [--bind 127.0.0.1] [--projects FILE]

FILE lists one project directory per line (default ~/.config/claude-sandbox/projects) and is
re-read on every request. A line may be a glob (`~/code/*`); a match ending in `.git` stands for
its repo, so `~/code/*/.git` lists only the git checkouts. Sessions belong to this process:
stopping the server stops them.
"""
import argparse
import base64
import fcntl
import glob
import json
import os
import pty
import queue
import re
import secrets
import signal
import socket
import struct
import subprocess
import termios
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
RUN_SH = HERE.parent / "run.sh"
RUN_ID = re.compile(r"[0-9a-f]{6}")
# git-workspace's per-run branch, <prefix>/<yyyymmdd>-<RUN_ID>: what makes a PR resumable.
RUN_BRANCH = re.compile(r".+/\d{8}-([0-9a-f]{6})")
SCROLLBACK = 256 * 1024  # bytes replayed to a browser that (re)opens a terminal

sessions = {}
lock = threading.Lock()  # guards `sessions` and every session's buf/listeners/exit


def projects(file):
    try:
        lines = [line.strip() for line in Path(file).read_text().splitlines()]
    except FileNotFoundError:
        return []
    found = []
    for line in lines:
        if not line or line.startswith("#"):
            continue
        path = str(Path(line).expanduser())
        if not glob.has_magic(path):
            found.append(path)
            continue
        # A pattern stands for every directory it matches now, so a new checkout shows up on the
        # next request; a match named .git stands for its repo (`~/code/*/.git`: git repos only).
        for match in sorted(glob.glob(path)):
            match = Path(match)
            if match.name == ".git":
                found.append(str(match.parent))
            elif match.is_dir():
                found.append(str(match))
    return list(dict.fromkeys(found))  # a project listed twice shows once


def command(kind, run_id):
    if kind == "shell":
        return [os.environ.get("SHELL", "/bin/sh")]
    return [str(RUN_SH), "--resume" if kind == "resume" else "--run-id", run_id]


class Session:
    def __init__(self, project, kind, run_id):
        self.id = secrets.token_hex(4)
        self.project, self.kind, self.run_id = project, kind, run_id
        self.started, self.exit = time.time(), None
        self.buf, self.listeners = bytearray(), []
        argv = command(kind, run_id)
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            try:
                os.chdir(project)
                os.execvpe(argv[0], argv, {**os.environ, "TERM": "xterm-256color"})
            finally:
                os._exit(127)
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        while True:
            try:
                data = os.read(self.fd, 65536)
            except OSError:  # EIO: the child side of the pty is gone
                break
            if not data:
                break
            with lock:
                self.buf += data
                del self.buf[:-SCROLLBACK]
                for q in self.listeners:
                    q.put(data)
        code = os.waitstatus_to_exitcode(os.waitpid(self.pid, 0)[1])
        with lock:
            self.exit = code
            for q in self.listeners:
                q.put(None)

    def write(self, data):
        while data and self.exit is None:
            data = data[os.write(self.fd, data):]

    def resize(self, cols, rows):
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def stop(self):
        if self.exit is not None:
            return
        try:
            os.killpg(self.pid, signal.SIGHUP)  # pty.fork made the child a session leader
        except ProcessLookupError:
            pass
        if self.kind != "shell":
            # The docker client forwards SIGHUP rather than dying of it, and what the container
            # does with it is the agent's business — so remove the container by the name run.sh
            # gave it. Before `docker run` there is none yet, and this is a no-op.
            subprocess.Popen(["docker", "rm", "-f", f"sandbox-{self.run_id}"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def json(self):
        return {k: getattr(self, k) for k in ("id", "project", "kind", "run_id", "started", "exit")}


def start(project, kind, run_id):
    if kind == "run":
        run_id = secrets.token_hex(3)
    elif kind == "shell":
        run_id = None
    elif kind != "resume" or not RUN_ID.fullmatch(run_id or ""):
        raise ValueError("kind must be run, shell, or resume with a 6-hex-char run_id")
    with lock:
        for s in sessions.values():
            # Two containers on one branch would push over each other: hand back the live one.
            if run_id and s.exit is None and (s.project, s.run_id) == (project, run_id):
                return s
        s = Session(project, kind, run_id)
        sessions[s.id] = s
        return s


def pull_requests(project):
    """Open PRs of a project, through the host's own `gh` login. {} when it has no origin."""
    if subprocess.run(["git", "-C", project, "remote", "get-url", "origin"],
                      capture_output=True).returncode:
        return {}
    try:
        done = subprocess.run(
            ["gh", "pr", "list", "--limit", "50", "--json", "number,title,url,headRefName,isDraft"],
            cwd=project, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return {"error": "the gh CLI is not installed on this machine"}
    except subprocess.TimeoutExpired:
        return {"error": "gh pr list timed out"}
    if done.returncode:
        return {"error": done.stderr.strip() or "gh pr list failed"}
    prs = json.loads(done.stdout)
    for pr in prs:
        match = RUN_BRANCH.fullmatch(pr["headRefName"])
        pr["run_id"] = match and match[1]
    return {"prs": prs}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, body, ctype="application/json"):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def guard(self):
        # This server types into terminals on your machine. Any web page you visit can aim
        # requests at localhost, so only our own page gets through: the Host check stops DNS
        # rebinding, the Origin check stops cross-site requests.
        host = self.headers.get("Host", "")
        if host in self.server.hosts and self.headers.get("Origin", f"http://{host}") == f"http://{host}":
            return True
        self.reply(403, {"error": "forbidden"})
        return False

    def session(self, sid):
        with lock:
            s = sessions.get(sid)
        if s is None:
            self.reply(404, {"error": "no such session"})
        return s

    def do_GET(self):
        if not self.guard():
            return
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        known = projects(self.server.projects_file)
        if url.path == "/":
            self.reply(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif url.path == "/api/state":
            with lock:
                live = [s.json() for s in sessions.values()]
            self.reply(200, {"projects": known, "projects_file": str(self.server.projects_file),
                             "sessions": live})
        elif url.path == "/api/prs" and query.get("project") in known:
            self.reply(200, pull_requests(query["project"]))
        elif m := re.fullmatch(r"/api/sessions/(\w+)/stream", url.path):
            if s := self.session(m[1]):
                self.stream(s)
        else:
            self.reply(404, {"error": "not found"})

    def do_POST(self):
        if not self.guard():
            return
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            if url.path == "/api/sessions":
                req = json.loads(body)
                if req.get("project") not in projects(self.server.projects_file):
                    raise ValueError("not a configured project")
                self.reply(200, start(req["project"], req.get("kind"), req.get("run_id")).json())
            elif m := re.fullmatch(r"/api/sessions/(\w+)/(input|resize|close)", url.path):
                s = self.session(m[1])
                if s is None:
                    return
                if m[2] == "input":
                    s.write(body)
                elif m[2] == "resize":
                    s.resize(int(query["cols"]), int(query["rows"]))
                elif s.exit is None:
                    s.stop()
                else:  # closing an ended session drops it from the list
                    with lock:
                        sessions.pop(s.id, None)
                    os.close(s.fd)
                self.reply(200, {})
            else:
                self.reply(404, {"error": "not found"})
        except (ValueError, KeyError, OSError, struct.error) as e:
            self.reply(400, {"error": str(e)})

    def stream(self, s):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        q = queue.Queue()
        with lock:  # backlog and subscription in one step, so no output is lost or doubled
            q.put(bytes(s.buf))
            if s.exit is None:
                s.listeners.append(q)
            else:
                q.put(None)
        try:
            while True:
                try:
                    data = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")  # also how a closed tab is noticed
                    self.wfile.flush()
                    continue
                if data is None:
                    self.wfile.write(b"event: exit\ndata: x\n\n")
                    break
                if data:
                    self.wfile.write(b"data: " + base64.b64encode(data) + b"\n\n")
                    self.wfile.flush()
        except OSError:
            pass
        finally:
            with lock:
                if q in s.listeners:
                    s.listeners.remove(q)


def local_names(bind):
    """Names this machine answers to on `bind`, as a browser would put them in the Host header."""
    if bind in ("127.0.0.1", "localhost"):
        return {"127.0.0.1", "localhost"}
    names = {"127.0.0.1", "localhost", socket.gethostname(), f"{socket.gethostname()}.local"}
    if bind not in ("0.0.0.0", ""):
        return names | {bind}
    try:
        out = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5).stdout
    except OSError:
        out = ""
    return names | {a for a in out.split() if ":" not in a}  # 0.0.0.0 is IPv4 only


def serve(port, projects_file, bind="127.0.0.1"):
    # Loopback by default: there is no login, so anyone who can reach the port can start
    # sandboxes as you. --bind 0.0.0.0 opens it to your network; the Host allowlist still
    # names only this machine's own addresses, so DNS rebinding stays blocked.
    server = ThreadingHTTPServer((bind, port), Handler)
    server.daemon_threads = True
    port = server.server_address[1]
    server.hosts = {f"{name}:{port}" for name in local_names(bind)}
    server.projects_file = projects_file
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--bind", default="127.0.0.1",
                        help="address to listen on; 0.0.0.0 for every interface (default: %(default)s)")
    parser.add_argument("--projects", type=Path,
                        default=Path.home() / ".config/claude-sandbox/projects",
                        help="file listing one project directory per line (default: %(default)s)")
    args = parser.parse_args()
    server = serve(args.port, args.projects, args.bind)
    print(f"Sandboxes: http://127.0.0.1:{server.server_address[1]}  (projects: {args.projects})",
          flush=True)
    if args.bind not in ("127.0.0.1", "localhost"):
        print("  also on: " + ", ".join(sorted(h for h in server.hosts if not h.startswith(("127.", "localhost")))),
              "  (no login: anyone who can reach it can start sandboxes as you)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for s in list(sessions.values()):
            s.stop()
