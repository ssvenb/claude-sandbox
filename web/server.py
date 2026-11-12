#!/usr/bin/env python3
"""Web UI to orchestrate sandboxes: a status page listing the configured projects with their
sessions and whatever their enabled plugins have to show (`run.sh --web`: open pull requests and
issues, say); a terminal page per session, each in its own tab; and VS Code in the browser
(`code serve-web`) on a run's checkout.

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
import sys
import shutil
import tempfile
import termios
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
RUN_SH = HERE.parent / "run.sh"
RUN_ID = re.compile(r"[0-9a-f]{6}")
SCROLLBACK = 256 * 1024  # bytes replayed to a browser that (re)opens a terminal

sessions = {}
described = {}  # project → what describe() last said about it
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
        return {**{k: getattr(self, k) for k in ("id", "project", "kind", "run_id", "started", "exit")},
                "workspace": checkout(self.project, self.run_id)}


def describe(project):
    """What the project's enabled plugins have for the page: `run.sh --web`, run in the project
    like a session would be. The page draws it without knowing which plugin said what."""
    try:
        done = subprocess.run([str(RUN_SH), "--web"], cwd=project, capture_output=True, text=True,
                              timeout=120)
        if done.returncode:  # run.sh's own complaint, e.g. about the project's .claude-sandbox.json
            raise ValueError(done.stderr.strip().splitlines()[-1] if done.stderr.strip() else "run.sh --web failed")
        found = json.loads(done.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        found = {"lists": [], "notes": [str(e)]}
    described[project] = found
    return found


def checkout(project, run_id):
    """A run's /workspace on this machine, where a plugin of the project says it keeps one."""
    pattern = described.get(project, {}).get("checkout")
    if not pattern or not run_id:
        return None
    return next(iter(sorted(glob.glob(pattern.replace("{run_id}", run_id)))), None)


vscode_lock = threading.Lock()
vscode_server = None  # (process, path of the unix socket it listens on)


def vscode():
    """The socket of the one `code serve-web` every editor tab talks to, started on first use.
    It serves any folder (`?folder=`), so one is enough for all projects and runs."""
    global vscode_server
    with vscode_lock:
        if vscode_server is None or vscode_server[0].poll() is not None:
            # VS Code in a browser is a shell on your account. A socket in a 0700 directory keeps
            # other local users out, and the only way in for a browser is Handler.tunnel, behind
            # the same guard as the terminals — so it needs no connection token of its own (one
            # would not survive anyway: the server refuses its token cookie on any navigation
            # another origin started, which every link from our page to a second port is).
            path = tempfile.mkdtemp(prefix="sandbox-vscode-") + "/socket"
            try:
                proc = subprocess.Popen(
                    ["code", "serve-web", "--socket-path", path, "--without-connection-token",
                     "--server-base-path", "/vscode", "--accept-server-license-terms"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True)  # a group of its own, to stop its children with it
            except FileNotFoundError:
                os.rmdir(os.path.dirname(path))
                raise ValueError("VS Code's `code` command is not installed on this machine") from None
            vscode_server = (proc, path)
        proc, path = vscode_server
        for _ in range(100):  # the first tab would otherwise load before it listens
            if proc.poll() is not None:
                raise ValueError(f"`code serve-web` exited with {proc.returncode}")
            if os.path.exists(path):
                return path
            time.sleep(0.1)
        raise ValueError("`code serve-web` did not start listening")


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

    def tunnel(self):
        """Pass one request under /vscode/ to `code serve-web`, and its answer back, as raw bytes:
        that carries its WebSockets too, and puts VS Code on our origin and behind our guard."""
        if not self.guard():
            return
        try:
            with vscode_lock:
                path = vscode_server and vscode_server[1]
            up = socket.socket(socket.AF_UNIX)
            up.connect(path)
        except (TypeError, OSError):  # never started (a stale tab, a restarted server), or gone
            return self.reply(502, {"error": "VS Code is not running: open it from the status page"})
        upgrade = "upgrade" in self.headers.get("Connection", "").lower()
        # One request per connection, or a later one would ride through unguarded.
        self.close_connection = True
        if not upgrade:
            del self.headers["Connection"]
            self.headers["Connection"] = "close"
        head = f"{self.command} {self.path} HTTP/1.1\r\n" + "".join(
            f"{k}: {v}\r\n" for k, v in self.headers.items()) + "\r\n"

        def upload():
            try:
                if upgrade:
                    while data := self.rfile.read1(65536):
                        up.sendall(data)
                    up.shutdown(socket.SHUT_RDWR)  # the browser hung up: so does VS Code's side
                else:
                    up.sendall(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            except (OSError, ValueError):
                pass

        try:
            with up:
                up.sendall(head.encode("latin-1"))
                threading.Thread(target=upload, daemon=True).start()
                while data := up.recv(65536):
                    self.connection.sendall(data)
        except OSError:
            pass
        if upgrade:  # unblocks upload(), which is still reading from the browser
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def route(self, mine):
        tunnel = self.path == "/vscode" or self.path.startswith(("/vscode/", "/vscode?"))
        (self.tunnel if tunnel else mine)()

    def do_GET(self):
        self.route(self.get)

    def do_POST(self):
        self.route(self.post)

    def do_PUT(self):  # nothing of ours, but VS Code may use any method
        self.route(lambda: self.reply(404, {"error": "not found"}))

    do_DELETE = do_HEAD = do_OPTIONS = do_PATCH = do_PUT

    def get(self):
        if not self.guard():
            return
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        known = projects(self.server.projects_file)
        if url.path == "/":
            self.reply(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif url.path == "/session":
            self.reply(200, (HERE / "session.html").read_bytes(), "text/html; charset=utf-8")
        elif url.path == "/api/state":
            with lock:
                live = [s.json() for s in sessions.values()]
            self.reply(200, {"projects": known, "projects_file": str(self.server.projects_file),
                             "sessions": live})
        elif url.path == "/api/project" and query.get("project") in known:
            self.reply(200, describe(query["project"]))
        elif m := re.fullmatch(r"/api/sessions/(\w+)/stream", url.path):
            if s := self.session(m[1]):
                self.stream(s)
        else:
            self.reply(404, {"error": "not found"})

    def post(self):
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
            elif url.path == "/api/vscode":
                # Only a folder this UI already knows: a session's checkout, as its plugins said.
                with lock:
                    s = sessions.get(json.loads(body).get("session"))
                folder = s and checkout(s.project, s.run_id)
                if not folder:
                    raise ValueError("no such session, or it has no checkout on this machine")
                vscode()
                self.reply(200, {"folder": folder})
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
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # so `finally` cleans up on a plain kill too
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
        if vscode_server:
            try:  # the `code` CLI leaves the server it spawned running when it is terminated
                os.killpg(vscode_server[0].pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            shutil.rmtree(os.path.dirname(vscode_server[1]), ignore_errors=True)
