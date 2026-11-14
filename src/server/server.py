#!/usr/bin/env python3
"""Web UI to orchestrate sandboxes: a dashboard of the configured projects with their sessions and
whatever their enabled plugins have to show (`run.sh --web`: open pull requests and issues, say);
a chat page per session, each in its own tab; a terminal page for a project's shell; and VS Code
in the browser (`code serve-web`) on a run's checkout.

Runs on the HOST, as you, next to run.sh — a session is `run.sh --chat` with the project as its
cwd: the agent behind its chat bridge (agents/<name>/chat.mjs), whose events (src/services/chat/chat-bridge.mjs)
come out of run.sh's stdout and go to the page as server-sent events, while prompts come back as
POSTs. The page is there from the first moment: what is typed while the sandbox still builds and
boots waits here and is handed to the agent the moment it is ready. A project's terminal is your
shell in a pty. Standard library only; the terminal page loads xterm.js from a CDN.

    src/server/server.py [--port 8787] [--bind 127.0.0.1] [--allow-host NAME]... [--projects FILE]

FILE lists one project directory per line (default ~/.config/claude-sandbox/projects) and is
re-read on every request. A line may be a glob (`~/code/*`); a match ending in `.git` stands for
its repo, so `~/code/*/.git` lists only the git checkouts. Sessions outlive this process: each
runs under src/server/holder.py, which keeps its output while no server listens, and a server that starts
takes back the sessions the last one left (STATE), running or ended — a restart cuts nothing off.
"""
import argparse
import base64
import glob
import json
import os
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
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent  # the checkout
HOLDER = HERE / "holder.py"
# A session's holder's socket and output, and what this server knew of it when it stopped.
STATE = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "claude-sandbox/sessions"
META = ("id", "project", "kind", "run_id", "started", "ui")
SAVED = ("exit", "events", "info", "todos", "tasks", "ready", "state", "waiting", "title", "activity", "said",
         "cost", "context", "sent", "offset")  # of a chat
RUN_SH = ROOT / "run.sh"
PLUGINS = ROOT / "plugins"
AGENTS = ROOT / "agents"
KERNEL = ROOT / "src/orchestrator/kernel.json"  # the settings of the sandbox itself, as plugins declare theirs
EXAMPLE = ROOT / ".claude-sandbox.example.json"  # what each plugin's section may hold
CONFIG = ".claude-sandbox.json"  # a project's own sandbox configuration, next to its checkout
RUN_ID = re.compile(r"[0-9a-f]{6}")
SCROLLBACK = 256 * 1024  # bytes replayed to a browser that (re)opens a terminal
KEEPALIVE = 15  # seconds between keepalives on a terminal's stream: how soon a closed tab is let go
# What the agent says it is doing, from the agent-status plugin's hook: an iTerm2-style user var in
# its output, `ESC ] 1337 ; SetUserVar=agent_status=<base64> BEL` (or ST in place of BEL).
STATUS = re.compile(rb"\x1b\]1337;SetUserVar=agent_status=([A-Za-z0-9+/=]*)(?:\x07|\x1b\\)")
STATES = {"working", "idle", "question"}
RS = b"\x1e"  # leads each chat event on a chat session's stdout; any other line is boot output
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|[\x00-\x08\x0b-\x1f]")
BOOT_LINES = 400  # of boot output kept for the page
EVENTS = 20000  # chat events kept per session, the oldest dropped first
QUIET = 3  # seconds without output after which an agent that reports nothing counts as idle
# A TUI at work redraws (its spinner, its timer) all the time, so "working" this long without a byte
# of output means it was interrupted before it could say it stopped (Esc fires no Stop hook).
STALE = 30

# The pages are one React app (web), built by `npm run build` into web/dist: its index.html
# for each of them (it picks the page by its path), and the scripts and styles that loads, under
# their own paths. Read on every request, so a new build shows on reload.
DIST = ROOT / "web/dist"
SERVICE = "claude-sandbox-web.service"  # install.sh registers it
PAGES = ("/", "/session", "/chat")
STATIC = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".map": "application/json",
          ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
          ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".txt": "text/plain; charset=utf-8"}
UNBUILT = ("The web UI is not built yet: run ./install.sh, or `npm ci && npm run build` in web, "
           "and reload this page.\n")

sessions = {}
described = {}  # project → what describe() last said about it
lock = threading.RLock()  # guards `sessions` and every session's buf/listeners/exit


def static(path):
    """The built file under web/dist that a URL path names, or None: only what a build puts
    there for a page to load (scripts, styles, fonts, pictures; not index.html, which is the
    pages'), and nothing outside it (no `..`, no symlink out of it)."""
    if not path.startswith("/") or "\\" in path or "\0" in path:
        return None
    root = DIST.resolve()
    file = (root / path.lstrip("/")).resolve()
    if file.suffix not in STATIC or not file.is_relative_to(root) or not file.is_file():
        return None
    return file


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


def command(kind, run_id, task=None, chat=False):
    if kind == "shell":  # the project's terminal: your own shell, on this machine, in the project
        return [os.environ.get("SHELL", "/bin/sh")]
    return [str(RUN_SH), "--resume" if kind == "resume" else "--run-id", run_id] \
        + (["--task", task] if task else []) + (["--chat"] if chat else [])


class Session:
    """A terminal: a project's shell, or an agent's own TUI (`"ui": "terminal"`), in a pty, held by
    src/server/holder.py so it outlives this server."""
    ui, mode = "terminal", "pty"

    def __init__(self, project, kind, run_id, task=None):
        self.id = secrets.token_hex(4)
        self.project, self.kind, self.run_id = project, kind, run_id
        self.started, self.exit = time.time(), None
        self._fresh()
        self.dir = STATE / self.id
        self.dir.mkdir(parents=True)
        (self.dir / "meta.json").write_text(json.dumps({k: getattr(self, k) for k in META}))
        try:
            hold(self.dir, self.mode, self.argv(task), project)
            self._attach(0)
        except OSError:
            shutil.rmtree(self.dir, ignore_errors=True)
            raise

    def argv(self, task):
        return command(self.kind, self.run_id, task)

    def _fresh(self):
        """What is not saved: a terminal's screen comes back from its holder."""
        self.buf, self.listeners = bytearray(), []
        self.said, self.output, self.tail = None, time.time(), b""  # see status()

    def _attach(self, start, tries=100):
        """Talks to its holder from here on: output from byte `start` on (negative: the last bytes)."""
        sock = socket.socket(socket.AF_UNIX)
        # A socket's path is at most 108 bytes: a longer one is reached through its folder's descriptor.
        folder = os.open(self.dir, os.O_PATH)
        try:
            for i in range(tries):
                try:
                    sock.connect(f"/proc/self/fd/{folder}/sock")
                    break
                except (FileNotFoundError, ConnectionRefusedError):
                    if i == tries - 1:
                        sock.close()
                        raise
                    time.sleep(0.05)
        finally:
            os.close(folder)
        self.sock, self.sending = sock, threading.Lock()
        self.pid = int((self.dir / "pid").read_text())
        self._ctl({"from": start})
        threading.Thread(target=self._pump, daemon=True).start()

    def _ctl(self, message):
        try:
            with self.sending:
                self.sock.sendall(json.dumps(message).encode() + b"\n")
        except OSError:  # its holder is gone: the pump says how it ended
            pass

    def _pump(self):
        code = -1  # its holder went without saying (killed, a reboot)
        try:
            for line in self.sock.makefile("rb"):
                message = json.loads(line)
                if "o" in message:
                    self._data(base64.b64decode(message["o"]))
                elif "from" in message:
                    with lock:
                        self._from(message["from"])
                elif "exit" in message:
                    code = message["exit"]
                    break
        except (OSError, ValueError):
            pass
        with lock:
            self._end(code)
            if self.id not in sessions:  # deleted while it ran: drop() left the rest to us
                self.close()
            else:
                self.save()

    def _from(self, start):
        pass

    def _data(self, data):
        self.output = time.time()
        # The marker may straddle two reads: look at it with the end of the last one.
        seen = self.tail + data
        for m in STATUS.finditer(seen):
            try:
                said = base64.b64decode(m[1]).decode()
            except ValueError:
                continue
            if said in STATES:
                self.said = said
        self.tail = seen[-96:]
        with lock:
            self.buf += data
            del self.buf[:-SCROLLBACK]
            for q in self.listeners:
                q.put(data)

    def _end(self, code):
        """Caller holds `lock`."""
        self.exit = code
        for q in self.listeners:
            q.put(None)

    def saved(self):
        return {"exit": self.exit}

    def save(self):
        """What a server started later takes it back from. Caller holds `lock`."""
        try:
            (self.dir / "state.json").write_text(json.dumps(self.saved()))
        except OSError:  # deleted
            pass

    @classmethod
    def restore(cls, folder, meta, saved):
        """A session the server before this one left: back to its holder, or ended."""
        s = cls.__new__(cls)
        for k in META:
            if k != "ui":
                setattr(s, k, meta[k])
        s.dir = folder
        s._fresh()
        s._load(saved)
        s.exit = saved.get("exit")
        if s.exit is None:
            try:
                s._attach(s._resume_from(), tries=1)
            except OSError:  # its holder is gone too: ended, maybe while no server listened
                out = folder / "out"
                if out.exists():
                    s._data(out.read_bytes()[max(0, s._resume_from()):])
                code = (folder / "exit").read_text() if (folder / "exit").exists() else "-1"
                with lock:
                    s._end(int(code))
                    s.save()
        return s

    def _load(self, saved):
        pass

    def _resume_from(self):
        return -SCROLLBACK

    def write(self, data):
        if self.exit is None:
            self._ctl({"in": base64.b64encode(data).decode()})

    def resize(self, cols, rows):
        self._ctl({"resize": [int(cols), int(rows)]})

    def stop(self):
        if self.exit is not None:
            return
        try:
            os.killpg(self.pid, signal.SIGHUP)  # pty.fork made the child a session leader
        except ProcessLookupError:
            pass
        if self.kind == "shell":
            return
        # The docker client forwards SIGHUP rather than dying of it, and what the container does
        # with it is the agent's business — so remove the container by the name run.sh gave it.
        # Before `docker run` there is none yet, and this is a no-op.
        subprocess.Popen(["docker", "rm", "-f", f"sandbox-{self.run_id}"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def status(self):
        """working, idle or question while it runs (None once it has ended, and for a terminal):
        what the agent last said it is doing, else a guess from whether output is flowing."""
        if self.exit is not None or self.kind == "shell":
            return None
        quiet = time.time() - self.output
        if self.said == "working" and quiet > STALE:
            return "idle"
        return self.said or ("working" if quiet < QUIET else "idle")

    def close(self):
        """Lets go of what an ended session still holds, its saved state too. Caller holds `lock`."""
        if hasattr(self, "sock"):
            self.sock.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def json(self):
        return {**{k: getattr(self, k) for k in ("id", "project", "kind", "run_id", "started", "exit", "ui")},
                "status": self.status(), "workspace": checkout(self.project, self.run_id),
                "items": live_items(self.project, self.run_id) if self.exit is None and self.kind != "shell" else []}


IMAGE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")
IMAGES, IMAGE_BYTES = 8, 5 << 20  # to a prompt, and each one's size: what the model's API takes


def pictures(images):
    """The pictures pasted into a prompt, checked: each its media type and its bytes in base64."""
    if images is None:
        return []
    if not isinstance(images, list) or len(images) > IMAGES:
        raise ValueError(f"a prompt takes up to {IMAGES} images")
    for p in images:
        if not isinstance(p, dict) or p.get("type") not in IMAGE_TYPES or not isinstance(p.get("data"), str):
            raise ValueError("an image is a PNG, JPEG, GIF or WebP")
        if len(p["data"]) * 3 // 4 > IMAGE_BYTES:
            raise ValueError("an image is at most 5 MB")
        try:
            base64.b64decode(p["data"], validate=True)
        except ValueError:
            raise ValueError("an image's data is base64") from None
    return [{"type": p["type"], "data": p["data"]} for p in images]


FILES, FILE_BYTES = 8, 10 << 20  # files attached to a prompt, and each one's size


def uploads(files):
    """The files attached to a prompt that are not pictures, checked: each its name and its bytes in base64."""
    if files is None:
        return []
    if not isinstance(files, list) or len(files) > FILES:
        raise ValueError(f"a prompt takes up to {FILES} files")
    for f in files:
        if not isinstance(f, dict) or not isinstance(f.get("name"), str) or not isinstance(f.get("data"), str):
            raise ValueError("a file is its name and its data")
        if not f["name"].strip() or "/" in f["name"] or "\\" in f["name"] or "\0" in f["name"] or f["name"] in (".", ".."):
            raise ValueError("a file's name is a plain name, without a folder")
        if len(f["data"]) * 3 // 4 > FILE_BYTES:
            raise ValueError("a file is at most 10 MB")
        try:
            base64.b64decode(f["data"], validate=True)
        except ValueError:
            raise ValueError("a file's data is base64") from None
    return [{"name": f["name"], "data": f["data"]} for f in files]


def tool_label(name, given):
    """A tool call in a few words, for a session's row: what it runs, reads or looks for."""
    given = given if isinstance(given, dict) else {}
    for key in ("description", "command", "file_path", "path", "pattern", "query", "url", "prompt"):
        if isinstance(given.get(key), str) and given[key].strip():
            return f"{name}: {given[key].strip().splitlines()[0]}"[:160]
    return name


class Chat(Session):
    """An agent behind its chat bridge: `run.sh --chat` on pipes. Its stdout is boot output until
    the bridge speaks, then chat events (src/services/chat/chat-bridge.mjs), each line led by RS. Every
    event is kept in `events` so a page opened later (or again) starts from the whole
    conversation; streamed text is folded into the block it belongs to on the way in."""
    ui, mode = "chat", "pipe"

    def __init__(self, project, kind, run_id, task=None, images=None):
        super().__init__(project, kind, run_id)
        if task or images:
            self.prompt(task or "", images)

    def argv(self, task):
        return command(self.kind, self.run_id, None, True)

    def _fresh(self):
        self.listeners, self.events = [], []
        self.tasks = []  # what its agent runs in the background right now
        self.ready, self.state, self.waiting = False, "idle", []  # (event, command) of prompts typed before `ready`
        self.info, self.todos = {}, []
        self.title = self.activity = self.said = ""
        self.cost, self.context, self.sent = None, None, 0
        self.blocks, self.tools, self.boot = {}, {}, None  # where streamed text, results and boot lines go
        self.offset, self.partial = 0, b""  # how much of its output `events` has taken in, and the line it is in

    def saved(self):
        return {k: getattr(self, k) for k in SAVED}

    def _load(self, saved):
        for k in SAVED:
            if k in saved:
                setattr(self, k, saved[k])
        # Streamed text and results go into the event they belong to, and a waiting prompt is the
        # very event the page shows: one object each, as they were before the save.
        self.blocks = {e.get("id"): e for e in self.events if e["type"] == "text"}
        self.tools = {e.get("id"): e for e in self.events if e["type"] == "tool"}
        self.boot = self.events[-1] if self.events and self.events[-1]["type"] == "boot" else None
        users = {e.get("id"): e for e in self.events if e["type"] == "user"}
        self.waiting = [users.get(w.get("id"), w) for w in self.waiting]

    def _resume_from(self):
        return self.offset

    def _from(self, start):
        self.offset, self.partial = start, b""

    def _data(self, data):
        *lines, self.partial = (self.partial + data).split(b"\n")
        for raw in lines:
            self._line(raw)

    def _line(self, raw):
        with lock:
            self.offset += len(raw) + 1
            if raw.startswith(RS):
                try:
                    event = json.loads(raw[1:])
                except ValueError:
                    return
                if isinstance(event, dict) and isinstance(event.get("type"), str):
                    self._take(event)
                return
            # A progress line redraws itself with carriage returns: its last state is what counts.
            text = ANSI.sub("", raw.decode(errors="replace").rstrip("\r").split("\r")[-1]).rstrip()
            if text:
                self._take({"type": "boot", "text": text})

    def _end(self, code):
        if self.partial:  # its last line, without a newline
            self._line(self.partial)
            self.partial = b""
        self.exit, self.tasks = code, []
        self._tell({"type": "exit", "code": code}, keep=True)
        for q in self.listeners:
            q.put(None)

    def _tell(self, event, keep=False):
        """To every open page, and into the log when a page opened later needs it too."""
        if keep:
            self.events.append(event)
            del self.events[:-EVENTS]
        for q in self.listeners:
            q.put(event)

    def _take(self, e):
        """One event from the bridge (or a line of boot output). Caller holds `lock`."""
        kind = e["type"]
        if kind == "boot":  # one growing entry, so the log is not a line per build step
            if self.boot is None or self.events[-1:] != [self.boot]:
                self.boot = {"type": "boot", "text": ""}
                self.events.append(self.boot)
            self.boot["text"] = "\n".join((self.boot["text"] + "\n" + e["text"]).lstrip("\n").splitlines()[-BOOT_LINES:])
            return self._tell(e)
        if kind in ("delta", "text"):
            block = self.blocks.get(e.get("id"))
            if block is None:
                block = self.blocks[e.get("id")] = {**e, "type": "text", "text": ""}
                self.events.append(block)
            block["text"] = block["text"] + e.get("text", "") if kind == "delta" else e.get("text", "")
            if block.get("kind") != "thinking" and not block.get("parent"):
                self.said = block["text"].strip()[-400:]
            return self._tell(e)
        if kind == "tool":
            tool = self.tools.get(e.get("id"))
            if tool is None:
                tool = self.tools[e.get("id")] = dict(e)
                self.events.append(tool)
            else:
                tool.update(e)
            if not e.get("parent"):
                self.activity = tool_label(str(e.get("name")), e.get("input"))
            return self._tell(e)
        if kind == "result":
            tool = self.tools.get(e.get("id"))
            if tool is not None:
                tool.update(output=e.get("output", ""), error=bool(e.get("error")), done=not e.get("partial"))
            return self._tell(e)
        if kind == "status":
            if e.get("state") in STATES:
                self.state = e["state"]
                if self.state != "working":
                    self.activity = ""
            return self._tell({"type": "status", "state": self.status()})
        if kind == "ready":
            self.info = {**self.info, **{k: v for k, v in e.items() if k != "type" and v is not None}}
            first, self.ready = not self.ready, True
            self._tell({"type": "ready", **self.info})
            if first:  # what was typed while the sandbox started, in the order it was typed
                waiting, self.waiting = self.waiting, []
                for event, command in waiting:
                    event.pop("queued", None)
                    self._send(command)
                    self._tell({"type": "sent", "id": event["id"]})
                if waiting:
                    self.state = "working"
                self._tell({"type": "status", "state": self.status()})
            return
        if kind in ("model", "effort"):
            self.info[kind] = e.get("id" if kind == "model" else "level")
            return self._tell(e)
        if kind == "todos":
            self.todos = e.get("items") if isinstance(e.get("items"), list) else []
            return self._tell(e)
        if kind == "tasks":  # the whole set each time: a page opened later gets the latest
            self.tasks = [t for t in e.get("items") or [] if isinstance(t, dict)] if isinstance(e.get("items"), list) else []
            return self._tell(e)
        if kind == "asked":
            for ask in self.events:
                if ask.get("type") == "ask" and ask.get("id") == e.get("id"):
                    ask["done"] = True
            return self._tell(e)
        if kind == "turn":
            if isinstance(e.get("cost"), (int, float)):
                self.cost = e["cost"]
            if isinstance(e.get("context"), dict):
                self.context = e["context"]
        if kind in ("hello", "progress"):
            return self._tell(e)
        self._tell(e, keep=True)  # user, ask, turn, notice, and whatever a bridge adds

    def _send(self, command):
        self._ctl({"in": base64.b64encode(json.dumps(command).encode() + b"\n").decode()})

    def prompt(self, text, images=None, files=None):
        """A message of the user's, with the pictures pasted into it and the files attached: to the
        agent at once, or kept until it is ready. Of a file, the page's events keep only its name."""
        images, files = pictures(images), uploads(files)
        if not isinstance(text, str) or not (text.strip() or images or files):
            raise ValueError("a prompt is text")
        with lock:
            if self.exit is not None:
                raise ValueError("this session has ended: resume it to go on")
            self.sent += 1
            event = {"type": "user", "id": f"u{self.sent}", "text": text, **({"images": images} if images else {}),
                     **({"files": [f["name"] for f in files]} if files else {})}
            self.title = self.title or " ".join(text.split())[:140] or ("File" if files and not images else "Image")
            command = {"type": "prompt", "text": text, **({"images": images} if images else {}), **({"files": files} if files else {})}
            if self.ready:
                self._send(command)
                self.state = "working"
            else:
                event["queued"] = True
                self.waiting.append((event, command))
            self._tell(event, keep=True)
            self._tell({"type": "status", "state": self.status()})

    def tell(self, command):
        """interrupt, answer, model, effort, task: straight to the bridge, which knows what they mean."""
        with lock:
            if command.get("type") == "answer":
                for ask in self.events:
                    if ask.get("type") == "ask" and ask.get("id") == command.get("id"):
                        ask["answers"] = None if command.get("cancel") else command.get("answers")
            if self.ready and self.exit is None:
                self._send(command)

    def snapshot(self):
        """Everything a page needs to draw the session from nothing. Caller holds `lock`."""
        return {"type": "snapshot", "events": self.events, "info": self.info, "todos": self.todos, "tasks": self.tasks,
                "ready": self.ready, "status": self.status(), "session": self.json()}

    def write(self, data):
        raise ValueError("a chat takes prompts, not keystrokes")

    resize = write

    def stop(self):
        if self.exit is None:
            self._ctl({"eof": True})
        super().stop()

    def status(self):
        """starting until the agent is ready, then what its bridge says: working, idle, question."""
        if self.exit is not None:
            return None
        return self.state if self.ready else "starting"

    def json(self):
        status = self.status()
        if status == "idle" and self.tasks:  # its turn is over, but what it started in the background runs on
            status = "working"
        return {**super().json(), "status": status, "title": self.title, "activity": self.activity, "said": self.said,
                "agent": self.info.get("agent"), "model": self.info.get("model"), "cost": self.cost,
                "context": self.context, "waiting": len(self.waiting), "todos": self.todos}


def describe(project, keep=False):
    """What the project's enabled plugins have for the page: `run.sh --web`, run in the project
    like a session would be. The page draws it without knowing which plugin said what. With
    `keep`, a failure leaves the last description standing instead of replacing it."""
    try:
        done = subprocess.run([str(RUN_SH), "--web"], cwd=project, capture_output=True, text=True,
                              timeout=120)
        if done.returncode:  # run.sh's own complaint, e.g. about the project's .claude-sandbox.json
            raise ValueError(done.stderr.strip().splitlines()[-1] if done.stderr.strip() else "run.sh --web failed")
        found = json.loads(done.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        if keep and project in described:
            return described[project]
        found = {"lists": [], "notes": [str(e)]}
    described[project] = found
    return found


def _manifest(path):
    try:
        found = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) else None


def plugin_manifests():
    """Every plugin the sandbox ships, as its manifest says, for the page's configuration dialog:
    the settings it declares, and its section from the example config."""
    try:
        example = json.loads(EXAMPLE.read_text()).get("plugins", {})
    except (OSError, ValueError):
        example = {}
    found = []
    for manifest in sorted(PLUGINS.glob("*/plugin.json")):
        meta = _manifest(manifest)
        if meta is None:
            continue
        name = manifest.parent.name
        found.append({"name": name, "description": meta.get("description", ""),
                      "defaultEnabled": bool(meta.get("defaultEnabled")),
                      "requiredAgent": meta.get("requiredAgent"), "example": example.get(name),
                      "settings": meta.get("settings", [])})
    return found


def agent_manifests():
    """Every agent the sandbox ships, with the settings it declares."""
    found = []
    for manifest in sorted(AGENTS.glob("*/agent.json")):
        meta = _manifest(manifest)
        if meta is not None:
            found.append({"name": manifest.parent.name, "description": meta.get("description", ""),
                          "settings": meta.get("settings", [])})
    return found


def kernel_manifest():
    """The settings of the sandbox itself, outside any agent or plugin."""
    meta = _manifest(KERNEL) or {}
    return {"description": meta.get("description", ""), "settings": meta.get("settings", [])}


def read_config(project):
    """A project's .claude-sandbox.json: what it holds now ({} without one), and where it is."""
    path = Path(project) / CONFIG
    try:
        config = json.loads(path.read_text())
    except FileNotFoundError:
        config = {}
    except ValueError as e:
        raise ValueError(f"{path} is not valid JSON ({e}): fix it by hand first")
    if not isinstance(config, dict):
        raise ValueError(f"{path} must hold a JSON object: fix it by hand first")
    return {"file": str(path), "exists": path.exists(), "config": config, "kernel": kernel_manifest(),
            "agents": agent_manifests(), "plugins": plugin_manifests()}


def check_config(config):
    """What run.sh would refuse, refused before it lands in the file (it reads the rest itself)."""
    if not isinstance(config, dict):
        raise ValueError("the configuration must be a JSON object")
    plugins = config.get("plugins", {})
    if not isinstance(plugins, dict):
        raise ValueError(".plugins must be an object keyed by plugin name")
    for name, section in plugins.items():
        if not isinstance(section, dict):
            raise ValueError(f".plugins[\"{name}\"] must be an object")
        if section.get("enabled", True) not in (True, False, 0, 1):
            raise ValueError(f".plugins[\"{name}\"].enabled must be true or false")
    env = config.get("env", {})
    if not isinstance(env, dict) or any(isinstance(v, (dict, list)) for v in env.values()):
        raise ValueError(".env must be an object of scalar values")
    # What the kernel, the agents and the plugins declare is checked against its declared type;
    # anything else is left to run.sh and the plugins, as before.
    declared = kernel_manifest()["settings"] + [s for a in agent_manifests() for s in a["settings"]]
    for p in plugin_manifests():
        declared += [s for s in p["settings"] if "env" in s]
        section = plugins.get(p["name"], {})
        for spec in p["settings"]:
            if "key" in spec and spec["key"] in section:
                check_setting(spec, section[spec["key"]], f'.plugins["{p["name"]}"].{spec["key"]}')
    for spec in declared:
        if spec.get("env") in env:
            check_setting(spec, env[spec["env"]], f".env.{spec['env']}", in_env=True)


def check_setting(spec, value, where, in_env=False):
    """One value against the type its owner declared for it (see README, "Declaring settings").
    An .env value is a scalar that run.sh exports as a string, so there it may be spelled as one."""
    kind = spec.get("type", "string")
    if value is None:
        raise ValueError(f"{where} must not be null: leave it out instead")
    if in_env:
        text = str(value).lower() if isinstance(value, bool) else str(value)
        if kind == "boolean" and text not in ("0", "1", "true", "false"):
            raise ValueError(f"{where} must be 0 or 1")
        if kind == "integer" and not re.fullmatch(r"-?[0-9]+", text):
            raise ValueError(f"{where} must be a whole number")
        if kind == "enum" and text not in spec.get("choices", []):
            raise ValueError(f"{where} must be one of {', '.join(spec.get('choices', []))}")
        if spec.get("pattern") and not re.fullmatch(spec["pattern"], text):
            raise ValueError(f"{where} is not in the expected format")
        return
    if kind == "boolean":
        ok = isinstance(value, bool)
    elif kind in ("string", "path"):
        ok = isinstance(value, str) and not (spec.get("pattern") and not re.fullmatch(spec["pattern"], value))
    elif kind == "text":
        ok = isinstance(value, str) or (isinstance(value, list) and all(isinstance(v, str) for v in value))
    elif kind == "integer":
        ok = isinstance(value, int) and not isinstance(value, bool) \
            and spec.get("min", value) <= value <= spec.get("max", value)
    elif kind == "enum":
        ok = value in spec.get("choices", [])
    elif kind == "list":
        if not isinstance(value, list):
            raise ValueError(f"{where} must be a list")
        for i, item in enumerate(value):
            check_setting(spec.get("items", {"type": "string"}), item, f"{where}[{i}]")
        return
    elif kind == "map":
        ok = isinstance(value, dict) and all(isinstance(v, (str, int, float)) and not isinstance(v, bool)
                                             for v in value.values())
    elif kind == "object":
        if not isinstance(value, dict):
            raise ValueError(f"{where} must be an object")
        for field in spec.get("fields", []):
            if not shown(field, value, spec["fields"]):
                continue
            key = field["key"]
            if key in value:
                check_setting(field, value[key], f"{where}.{key}")
            elif field.get("required"):
                raise ValueError(f"{where}.{key} is required")
        return
    else:  # json: anything JSON holds
        ok = True
    if not ok:
        raise ValueError(f"{where} is not a valid {kind}" + (
            f" (one of {', '.join(map(str, spec['choices']))})" if kind == "enum" else ""))


def shown(field, siblings, fields):
    """Whether a field applies, given the object it sits in: its `when` names the values a sibling
    must have, that sibling's declared default while it is unset."""
    for key, allowed in field.get("when", {}).items():
        default = next((f.get("default") for f in fields if f.get("key") == key), None)
        if siblings.get(key, default) not in allowed:
            return False
    return True


def write_config(project, config):
    """Replaces the project's .claude-sandbox.json in one step, so run.sh never reads half a file."""
    check_config(config)
    path = Path(project) / CONFIG
    fd, tmp = tempfile.mkstemp(dir=project, prefix=f".{CONFIG}.")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(config, f, indent=2)
            f.write("\n")
        try:
            os.chmod(tmp, path.stat().st_mode & 0o777)
        except FileNotFoundError:
            os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def run_items(said, run_id):
    """What the project's plugins put on a run's session row: its own items, run items and
    section items tied to the run."""
    items = [*said.get("session_items", []), *said.get("run_items", []),
             *(i for lst in said.get("lists", []) for i in lst.get("items", []))]
    return [i for i in items if run_id and i.get("run_id") == run_id]


def offers(s):
    """What deleting session s offers to tidy up: the items of its run carrying an `on_delete`
    (its open pull request), as the plugins last described the project. Nothing while another
    session of the run is listed: the run is not over. Caller holds `lock`."""
    if any(o is not s and (o.project, o.run_id) == (s.project, s.run_id) for o in sessions.values()):
        return []
    return [i for i in run_items(described.get(s.project, {}), s.run_id) if isinstance(i.get("on_delete"), dict)]


def tidy(s, urls, offered):
    """For a deleted session: the `on_delete` of each item of its run whose url the page names
    (its user said yes to each), as `run.sh --web-action`. Only what a plugin offered for this
    very run, never what the request spells out. Returns what failed, one line each."""
    failed = []
    for item in offered:
        act = item["on_delete"]
        if item.get("url") not in urls:
            continue
        try:
            done = subprocess.run([str(RUN_SH), "--web-action", str(act["plugin"]), str(act["action"]),
                                   str(act.get("arg", ""))], cwd=s.project, capture_output=True,
                                  text=True, timeout=120)
            if done.returncode:
                said = done.stderr.strip()
                failed.append(f"{item.get('ref') or item.get('title')}: "
                              + (said.splitlines()[-1] if said else "run.sh --web-action failed"))
        except (OSError, KeyError, subprocess.TimeoutExpired) as e:
            failed.append(f"{item.get('ref') or item.get('title')}: {e}")
    return failed


def live_items(project, run_id):
    """What the project's plugins publish for a run while it runs (web_live_items: the ports its
    servers listen on), read afresh: it changes faster than the project is described."""
    found = []
    for file in described.get(project, {}).get("live", []) if run_id else []:
        try:
            items = json.loads(Path(file).read_text())
        except (OSError, ValueError):  # nothing published yet, or caught mid-write
            continue
        if isinstance(items, list):
            found += [i for i in items if isinstance(i, dict) and i.get("run_id") == run_id]
    return found


def checkout(project, run_id):
    """A run's /workspace on this machine, where a plugin of the project says it keeps one."""
    pattern = described.get(project, {}).get("checkout")
    if not pattern or not run_id:
        return None
    return next(iter(sorted(glob.glob(pattern.replace("{run_id}", run_id)))), None)


vscode_lock = threading.Lock()
vscode_server = None  # (process, path of the unix socket it listens on)


def vscode_cli():
    """The VS Code CLI that can `serve-web`. Not the desktop `code` launcher where there is one:
    it only passes the command on to the CLI it bundles, and the snap's launcher (which puts
    `--no-sandbox` first) exits 0 without serving at all, so go to that bundled CLI directly."""
    code = shutil.which("code")
    if not code:
        raise ValueError("VS Code's `code` command is not installed on this machine")
    for cli in (Path(os.path.realpath(code)).with_name("code-tunnel"),  # .deb/.rpm: /usr/share/code/bin
                Path(code).parent.parent / "code/current/usr/share/code/bin/code-tunnel"):  # snap
        if os.access(cli, os.X_OK):
            return str(cli)
    return code  # the standalone CLI (code.visualstudio.com/#alt-downloads) is `code` itself


# Machine settings every VS Code tab gets. Copilot's chat pane has no place here: the agent works
# in the sandbox, VS Code is for reading and editing what it did.
VSCODE_SETTINGS = {"chat.disableAIFeatures": True}


def vscode_data():
    """VS Code's data directory (extensions, machine settings), with VSCODE_SETTINGS applied over
    what is already there: settings changed in VS Code itself, under "Remote", are kept."""
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "claude-sandbox/vscode"
    file = data / "data/Machine/settings.json"
    file.parent.mkdir(parents=True, exist_ok=True)
    try:
        settings = json.loads(file.read_text())
    except FileNotFoundError:
        settings = {}
    except ValueError:  # edited in VS Code, with comments: not ours to rewrite
        return data
    if settings | VSCODE_SETTINGS != settings:
        file.write_text(json.dumps(settings | VSCODE_SETTINGS, indent=2) + "\n")
    return data


def vscode():
    """The socket of the one `code serve-web` every editor tab talks to, started on first use.
    It serves any folder (`?folder=`), so one is enough for all projects and runs."""
    global vscode_server
    with vscode_lock:
        if vscode_server is None or vscode_server[0].poll() is not None:
            if vscode_server:  # it died: its socket and log go with it
                shutil.rmtree(os.path.dirname(vscode_server[1]), ignore_errors=True)
                vscode_server = None
            cli, data = vscode_cli(), vscode_data()
            # VS Code in a browser is a shell on your account. A socket in a 0700 directory keeps
            # other local users out, and the only way in for a browser is Handler.tunnel, behind
            # the same guard as the terminals — so it needs no connection token of its own (one
            # would not survive anyway: the server refuses its token cookie on any navigation
            # another origin started, which every link from our page to a second port is).
            run_dir = tempfile.mkdtemp(prefix="sandbox-vscode-")
            path = run_dir + "/socket"
            with open(run_dir + "/log", "wb") as log:
                proc = subprocess.Popen(
                    [cli, "serve-web", "--socket-path", path, "--without-connection-token",
                     "--server-base-path", "/vscode", "--server-data-dir", str(data),
                     "--accept-server-license-terms"],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                    start_new_session=True)  # a group of its own, to stop its children with it
            vscode_server = (proc, path)
        proc, path = vscode_server
        for _ in range(100):  # the first tab would otherwise load before it listens
            if proc.poll() is not None:
                said = Path(os.path.dirname(path), "log").read_text(errors="replace").strip()
                raise ValueError(f"`{proc.args[0]} serve-web` exited with {proc.returncode}"
                                 + (f": {said.splitlines()[-1]}" if said else ""))
            if os.path.exists(path):
                return path
            time.sleep(0.1)
        raise ValueError("`code serve-web` did not start listening")


scoped = []


def hold(folder, mode, argv, cwd):
    """Starts a session's process under src/server/holder.py, which outlives this server. Under systemd
    it goes into a scope of its own: restarting this server's unit stops everything in its cgroup."""
    if not scoped:
        unit = ["systemd-run", "--user", "--scope", "--quiet", "--collect", "--"]
        ok = os.environ.get("INVOCATION_ID") and shutil.which("systemd-run") and subprocess.run(
            unit + ["true"], capture_output=True).returncode == 0
        scoped.append(unit if ok else [])
    with open(folder / "log", "ab") as log:  # what the holder itself says, should it fail
        subprocess.Popen(scoped[0] + [sys.executable, str(HOLDER), str(folder), mode, "--", *argv], cwd=cwd,
                         start_new_session=True, stdin=subprocess.DEVNULL, stdout=log, stderr=log)


def restore():
    """Takes back the sessions the server before this one left, running or ended."""
    for meta in sorted(STATE.glob("*/meta.json"), key=lambda m: m.stat().st_mtime):
        state = meta.parent / "state.json"
        try:
            m = json.loads(meta.read_text())
            saved = json.loads(state.read_text()) if state.exists() else {}
            s = (Chat if m["ui"] == "chat" else Session).restore(meta.parent, m, saved)
        except (OSError, ValueError, KeyError) as e:
            print(f"  could not take back the session in {meta.parent}: {e}", file=sys.stderr, flush=True)
            continue
        with lock:
            sessions[s.id] = s


def drop(s):
    """Forget a session. Caller holds `lock`. A live one is stopped first, and what it holds let
    go of by its pump once it has ended, never under it."""
    if sessions.pop(s.id, None) and s.exit is not None:
        s.close()


def sync():
    """Pulls main into this checkout and runs install.sh; then, under systemd, restarts this server."""
    root = ROOT
    for step in (["git", "-C", str(root), "pull", "--ff-only", "origin", "main"], [str(root / "install.sh"), "--yes"]):
        done = subprocess.run(step, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if done.returncode:
            raise ValueError(f"{' '.join(step[:4])} failed:\n" + (done.stderr or done.stdout)[-2000:])
    if not os.environ.get("INVOCATION_ID"):  # systemd sets it in the services it starts
        return {"restarting": False}
    # Detached and a moment late, so this reply gets out before the restart takes the server down.
    subprocess.Popen(["sh", "-c", f"sleep 1; systemctl --user restart {SERVICE} || systemctl restart {SERVICE}"],
                     start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"restarting": True}


def start(project, kind, run_id, task=None, ui=None, images=None):
    """A new session, or the live one it would double. An agent's session is a chat unless
    `ui` is "terminal" (its own TUI in a pty, as `run.sh` in your terminal); a shell is a terminal."""
    if ui not in (None, "chat", "terminal"):
        raise ValueError("ui must be chat or terminal")
    images = pictures(images)
    if (task is not None or images) and (kind != "run" or not isinstance(task or "", str) or not ((task or "").strip() or images)):
        raise ValueError("a task starts a new run, and is text")
    if images and ui == "terminal":
        raise ValueError("a terminal takes no images")
    if kind == "run":
        run_id = secrets.token_hex(3)
    elif kind == "shell":
        run_id = None
    elif kind != "resume" or not RUN_ID.fullmatch(run_id or ""):
        raise ValueError("kind must be run, shell, or resume with a 6-hex-char run_id")
    with lock:
        title = ""
        for s in list(sessions.values()):
            if (s.project, s.run_id, s.kind == "shell") != (project, run_id, kind == "shell"):
                continue
            # Two containers on one branch would push over each other, and one terminal per
            # project is enough: hand back the live one. An ended one stays (its tab shows how it
            # ended) until the next one of its run, or of its project for a terminal, replaces it:
            # a run is one session however often it is resumed, and a resumed chat replays it.
            if s.exit is None:
                return s
            title = title or getattr(s, "title", "")
            drop(s)
        s = (Session if kind == "shell" or ui == "terminal" else Chat)(project, kind, run_id, task, *([images] if images else []))
        if isinstance(s, Chat):
            s.title = s.title or title
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
        if url.path in PAGES:
            try:
                self.reply(200, (DIST / "index.html").read_bytes(), "text/html; charset=utf-8")
            except OSError:
                self.reply(503, UNBUILT.encode(), "text/plain; charset=utf-8")
        elif (asset := static(url.path)) is not None:
            self.reply(200, asset.read_bytes(), STATIC[asset.suffix])
        elif url.path == "/api/state":
            with lock:
                live = [s.json() for s in sessions.values()]
            self.reply(200, {"projects": known, "projects_file": str(self.server.projects_file),
                             "sessions": live})
        elif url.path == "/api/project" and query.get("project") in known:
            self.reply(200, describe(query["project"]))
        elif url.path == "/api/config" and query.get("project") in known:
            try:
                self.reply(200, read_config(query["project"]))
            except ValueError as e:
                self.reply(400, {"error": str(e)})
        elif m := re.fullmatch(r"/api/sessions/(\w+)/offers", url.path):
            # What its page asks about before deleting it, one yes/no each.
            # Described afresh first: the pull request a run opened a moment ago is offered too,
            # and one closed or merged since is not.
            if s := self.session(m[1]):
                if s.kind != "shell":
                    describe(s.project, keep=True)
                with lock:
                    found = offers(s)
                self.reply(200, {"offers": [{k: i.get(k) for k in ("url", "ref", "title")}
                                            | {"ask": str(i["on_delete"].get("ask") or f"Tidy up {i.get('ref') or i.get('title')} too?")}
                                            for i in found]})
        elif m := re.fullmatch(r"/api/sessions/(\w+)/stream", url.path):
            if s := self.session(m[1]):
                if s.ui != "terminal":
                    return self.reply(400, {"error": "a chat has events, not a stream"})
                self.stream(s)
        elif m := re.fullmatch(r"/api/sessions/(\w+)/events", url.path):
            if s := self.session(m[1]):
                if s.ui != "chat":
                    return self.reply(400, {"error": "a terminal has a stream, not events"})
                self.events(s)
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
                self.reply(200, start(req["project"], req.get("kind"), req.get("run_id"), req.get("task"),
                                      req.get("ui"), req.get("images")).json())
            elif url.path == "/api/config":
                req = json.loads(body)
                if req.get("project") not in projects(self.server.projects_file):
                    raise ValueError("not a configured project")
                write_config(req["project"], req.get("config"))
                self.reply(200, read_config(req["project"]))
            elif url.path == "/api/vscode":
                # Only a folder this UI already knows: a session's checkout, as its plugins said.
                with lock:
                    s = sessions.get(json.loads(body).get("session"))
                folder = s and checkout(s.project, s.run_id)
                if not folder:
                    raise ValueError("no such session, or it has no checkout on this machine")
                vscode()
                self.reply(200, {"folder": folder})
            elif url.path == "/api/sync":
                self.reply(200, sync())
            elif m := re.fullmatch(r"/api/sessions/(\w+)/(prompt|interrupt|answer|model|effort|task)", url.path):
                s = self.session(m[1])
                if s is None:
                    return
                if s.ui != "chat":
                    raise ValueError("a terminal takes keystrokes, not prompts")
                req = json.loads(body) if body.strip() else {}
                if not isinstance(req, dict):
                    raise ValueError("the request must be a JSON object")
                if m[2] == "prompt":
                    s.prompt(req.get("text"), req.get("images"), req.get("files"))
                else:  # only the fields a bridge reads, under the name the path gave
                    s.tell({"type": m[2], **{k: req[k] for k in ("id", "answers", "cancel", "level") if k in req}})
                self.reply(200, {})
            elif m := re.fullmatch(r"/api/sessions/(\w+)/(input|resize|stop|delete)", url.path):
                s = self.session(m[1])
                if s is None:
                    return
                if m[2] == "input":
                    s.write(body)
                elif m[2] == "resize":
                    s.resize(int(query["cols"]), int(query["rows"]))
                elif m[2] == "stop":  # its container goes, its entry stays: to read, to resume
                    s.stop()
                else:  # gone from the list, stopped first if it still runs
                    # The urls of its run's items the page's user said yes to tidying up too.
                    req = json.loads(body) if body.strip() else {}
                    urls = req.get("tidy") if isinstance(req, dict) else None
                    if not isinstance(urls, list):
                        urls = []
                    s.stop()
                    with lock:
                        offered = offers(s)
                        drop(s)
                    failed = tidy(s, urls, offered)
                    self.reply(200, {"failed": failed})
                    return
                self.reply(200, {})
            else:
                self.reply(404, {"error": "not found"})
        except (ValueError, KeyError, OSError, struct.error) as e:
            self.reply(400, {"error": str(e)})

    def events(self, s):
        """A chat's events: the conversation so far in one snapshot, then each event as it comes."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        q = queue.Queue()
        with lock:  # snapshot and subscription in one step, so no event is lost or doubled
            first = json.dumps(s.snapshot()).encode()
            if s.exit is None:
                s.listeners.append(q)
            else:
                q.put(None)
        try:
            self.wfile.write(b"data: " + first + b"\n\n")
            self.wfile.flush()
            while True:
                try:
                    event = q.get(timeout=KEEPALIVE)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")  # also how a closed tab is noticed
                    self.wfile.flush()
                    continue
                if event is None:
                    break
                self.wfile.write(b"data: " + json.dumps(event).encode() + b"\n\n")
                self.wfile.flush()
        except OSError:
            pass
        finally:
            with lock:
                if q in s.listeners:
                    s.listeners.remove(q)

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
                    data = q.get(timeout=KEEPALIVE)
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
            # A closed tab only lets go of the stream: the session runs on until told to stop.
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


def ports_bind(bind, env):
    """Where the sessions' published ports listen: where the page does, so a port button works from
    wherever the page was opened — unless PORTS_BIND says otherwise (the shell's, or a project's)."""
    if env.get("PORTS_BIND") or bind in ("127.0.0.1", "localhost"):
        return env.get("PORTS_BIND")
    return bind or "0.0.0.0"


def serve(port, projects_file, bind="127.0.0.1", allow_hosts=()):
    # Loopback by default: there is no login, so anyone who can reach the port can start
    # sandboxes as you. --bind 0.0.0.0 opens it to your network; the Host allowlist still
    # names only this machine's own addresses (plus any --allow-host), so DNS rebinding stays blocked.
    server = ThreadingHTTPServer((bind, port), Handler)
    server.daemon_threads = True
    port = server.server_address[1]
    server.hosts = {f"{name}:{port}" for name in local_names(bind) | set(allow_hosts)}
    server.projects_file = projects_file
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--bind", default="127.0.0.1",
                        help="address to listen on; 0.0.0.0 for every interface (default: %(default)s)")
    parser.add_argument("--allow-host", action="append", default=[], metavar="NAME",
                        help="another name the page may be opened by, e.g. a VPN's DNS name (repeatable)")
    parser.add_argument("--projects", type=Path,
                        default=Path.home() / ".config/claude-sandbox/projects",
                        help="file listing one project directory per line (default: %(default)s)")
    args = parser.parse_args()
    if (bind := ports_bind(args.bind, os.environ)):
        os.environ["PORTS_BIND"] = bind  # for every run.sh this starts, sessions and --web alike
    restore()
    server = serve(args.port, args.projects, args.bind, args.allow_host)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # so `finally` cleans up on a plain kill too
    print(f"Sandboxes: http://127.0.0.1:{server.server_address[1]}  (projects: {args.projects})",
          flush=True)
    if args.bind not in ("127.0.0.1", "localhost"):
        print("  also on: " + ", ".join(sorted(h for h in server.hosts if not h.startswith(("127.", "localhost")))),
              "  (no login: anyone who can reach it can start sandboxes as you)", flush=True)
        print(f"  sessions publish their ports on {os.environ.get('PORTS_BIND', '127.0.0.1')}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        with lock:  # they run on: what the next server takes them back from
            for s in list(sessions.values()):
                s.save()
        if vscode_server:
            try:  # the `code` CLI leaves the server it spawned running when it is terminated
                os.killpg(vscode_server[0].pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            shutil.rmtree(os.path.dirname(vscode_server[1]), ignore_errors=True)
