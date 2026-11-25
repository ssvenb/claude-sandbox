#!/usr/bin/env python3
"""Web UI to orchestrate sandboxes: a dashboard of the configured projects with their sessions and
whatever their enabled plugins have to show (`run.sh --web`: open pull requests and issues, say);
a chat page per session, each in its own tab (a terminal page for one run with its agent's TUI); and what a
plugin serves itself (web_server: VS Code in the browser, say), on our origin under /plugins/<name>/.

Runs on the HOST, as you, next to run.sh — a session is `run.sh --project <name> --chat`: the agent behind its chat bridge (agents/<name>/chat.mjs), whose events (src/services/chat/chat-bridge.mjs)
come out of run.sh's stdout and go to the page as server-sent events, while prompts come back as
POSTs. The page is there from the first moment: what is typed while the sandbox still builds and
boots waits here and is handed to the agent the moment it is ready. There is no shell on this
machine: every session is a sandbox. The terminal page loads xterm.js from a CDN.

    src/server/server.py [--port 8787] [--bind 127.0.0.1] [--allow-host NAME]... [--projects DIR]

DIR holds a <name>.json per project (default ~/.config/claude-sandbox/projects), its settings and
the repo it works on, and is re-read on every request. Sessions outlive this process: each
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
import stat
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # src: the orchestrator's auth.py
from orchestrator import Die, auth, config as project_config  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent  # the checkout
HOLDER = HERE / "holder.py"
# A session's holder's socket and output, and what this server knew of it when it stopped.
STATE = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "claude-sandbox/sessions"
META = ("id", "project", "kind", "run_id", "started", "ui")
SAVED = ("exit", "events", "info", "todos", "tasks", "ready", "state", "waiting", "pending", "title", "activity",
         "said", "cost", "context", "sent", "offset", "sides", "sided")  # of a chat
# Where the page was last opened (http://<Host>), from the last request guard() let in: the address
# web_on_status is told a session's page by (on_status()).
page_origin = None
OFFERS = ("model", "models", "effort", "efforts", "commands")  # what an agent offers on `ready`; see agent_offers()
RUN_SH = ROOT / "run.sh"
PLUGINS = ROOT / "plugins"
AGENTS = ROOT / "agents"
KERNEL = ROOT / "src/orchestrator/kernel.json"  # the settings of the sandbox itself, as plugins declare theirs
EXAMPLE = ROOT / ".claude-sandbox.example.json"  # what each plugin's section may hold
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


def projects(directory):
    """The configured projects' names, a file each in `directory` (a list there is made into them)."""
    return project_config.project_names(project_config.projects_dir({"SANDBOX_PROJECTS_DIR": str(directory)}))


def config_file(project):
    return project_config.projects_dir(os.environ) / f"{project}.json"


def command(project, kind, run_id, task=None, chat=False, sets=None):
    return [str(RUN_SH), "--project", project, "--resume" if kind == "resume" else "--run-id", run_id] \
        + (["--task", task] if task else []) + (["--chat"] if chat else []) \
        + [arg for name, value in (sets or {}).items() for arg in ("--set", f"{name}={value}")]


class Session:
    """A terminal: an agent's own TUI (`"ui": "terminal"`), in a pty, held by
    src/server/holder.py so it outlives this server."""
    ui, mode = "terminal", "pty"

    def __init__(self, project, kind, run_id, task=None, sets=None, once=False):
        self.id = secrets.token_hex(4)
        self.project, self.kind, self.run_id = project, kind, run_id
        # What a plugin started it with (web_start): settings of this run alone, and whether it
        # goes by itself once its agent has finished.
        self.sets, self.once = sets or {}, once
        self.started, self.exit = time.time(), None
        self._fresh()
        self.dir = STATE / self.id
        self.dir.mkdir(parents=True)
        (self.dir / "meta.json").write_text(json.dumps({k: getattr(self, k) for k in (*META, "once")}))
        try:
            hold(self.dir, self.mode, self.argv(task), Path.home())
            self._attach(0)
        except OSError:
            shutil.rmtree(self.dir, ignore_errors=True)
            raise

    def argv(self, task):
        return command(self.project, self.kind, self.run_id, task, False, self.sets)

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
        s.sets, s.once = {}, bool(meta.get("once"))
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
        # The docker client forwards SIGHUP rather than dying of it, and what the container does
        # with it is the agent's business — so remove the container by the name run.sh gave it.
        # Before `docker run` there is none yet, and this is a no-op.
        subprocess.Popen(["docker", "rm", "-f", f"sandbox-{self.run_id}"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def status(self):
        """working, idle or question while it runs (None once it has ended, and for a terminal):
        what the agent last said it is doing, else a guess from whether output is flowing."""
        if self.exit is not None:
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

    def shown(self):
        """Its status as the page shows it, and web_on_status is told it (on_status)."""
        return self.status()

    def json(self):
        return {**{k: getattr(self, k) for k in ("id", "project", "kind", "run_id", "started", "exit", "ui")},
                "status": self.shown(), "workspace": checkout(self.project, self.run_id),
                "plugins": described.get(self.project, {}).get("plugins", []),
                "items": live_items(self.project, self.run_id) if self.exit is None else []}


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


def fold(e, events, blocks, tools):
    """A streamed event into the one it belongs to in `events`: text into its block, a tool call's
    input and its result into the call. Returns that event (none for a result without its call)."""
    kind = e["type"]
    if kind in ("delta", "text"):
        block = blocks.get(e.get("id"))
        if block is None:
            block = blocks[e.get("id")] = {**e, "type": "text", "text": ""}
            events.append(block)
        block["text"] = block["text"] + e.get("text", "") if kind == "delta" else e.get("text", "")
        return block
    tool = tools.get(e.get("id"))
    if kind == "tool":
        if tool is None:
            tool = tools[e.get("id")] = dict(e)
            events.append(tool)
        else:
            tool.update(e)
    elif tool is not None:  # its result
        tool.update(output=e.get("output", ""), error=bool(e.get("error")), done=not e.get("partial"))
    return tool


class Chat(Session):
    """An agent behind its chat bridge: `run.sh --chat` on pipes. Its stdout is boot output until
    the bridge speaks, then chat events (src/services/chat/chat-bridge.mjs), each line led by RS. Every
    event is kept in `events` so a page opened later (or again) starts from the whole
    conversation; streamed text is folded into the block it belongs to on the way in."""
    ui, mode = "chat", "pipe"

    def __init__(self, project, kind, run_id, task=None, images=None, **started):
        super().__init__(project, kind, run_id, **started)
        if task or images:
            self.prompt(task or "", images)

    def argv(self, task):
        return command(self.project, self.kind, self.run_id, None, True, self.sets)

    def _fresh(self):
        self.listeners, self.events = [], []
        self.tasks = []  # what its agent runs in the background right now
        self.ready, self.state, self.waiting = False, "idle", []  # (event, command) of prompts typed before `ready`
        self.info, self.todos = agent_offers().get(self.project, {}), []
        self.pending = {}  # model and effort picked before `ready`, sent ahead of the waiting prompts
        self.title = self.activity = self.said = ""
        self.cost, self.context, self.sent = None, None, 0
        self.blocks, self.tools, self.boot = {}, {}, None  # where streamed text, results and boot lines go
        self.offset, self.partial = 0, b""  # how much of its output `events` has taken in, and the line it is in
        self.finished = False  # its last turn ended, and well: when a session started `once` goes
        # Its side chats, where the run's conversation is asked about beside it: id → {id, title,
        # state, events}, the ids counted up (`sided`), and where each one's streamed text and results go.
        self.sides, self.sided, self.side_maps = {}, 0, {}

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
        self.waiting = [(users.get(e.get("id"), e), command) for e, command in self.waiting]
        self.side_maps = {sid: ({e.get("id"): e for e in side["events"] if e["type"] == "text"},
                                {e.get("id"): e for e in side["events"] if e["type"] == "tool"})
                          for sid, side in self.sides.items()}

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
        for side in self.sides.values():
            side["state"] = "idle"
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
        if e.get("side") is not None:
            return self._side(e)
        if kind == "boot":  # one growing entry, so the log is not a line per build step
            if self.boot is None or self.events[-1:] != [self.boot]:
                self.boot = {"type": "boot", "text": ""}
                self.events.append(self.boot)
            self.boot["text"] = "\n".join((self.boot["text"] + "\n" + e["text"]).lstrip("\n").splitlines()[-BOOT_LINES:])
            return self._tell(e)
        if kind in ("delta", "text", "tool", "result"):
            into = fold(e, self.events, self.blocks, self.tools)
            if kind == "tool" and not e.get("parent"):
                self.activity = tool_label(str(e.get("name")), e.get("input"))
            elif kind in ("delta", "text") and into.get("kind") != "thinking" and not into.get("parent"):
                self.said = into["text"].strip()[-400:]
            return self._tell(e)
        if kind == "status":
            if e.get("state") in STATES:
                self.state = e["state"]
                if self.state != "working":
                    self.activity = ""
            self._tell({"type": "status", "state": self.status()})
            return self._leave()
        if kind == "ready":
            self.info = {**self.info, **{k: v for k, v in e.items() if k != "type" and v is not None}}
            agent_offers({k: self.info[k] for k in OFFERS if k in self.info}, self.project)
            for command in self.pending.values():  # the pick shows until the agent says it took it
                self.info[command["type"]] = command.get("id", command.get("level"))
            first, self.ready = not self.ready, True
            self._tell({"type": "ready", **self.info})
            if first:  # what was picked and typed while the sandbox started, in that order
                pending, self.pending = self.pending, {}
                for command in pending.values():
                    self._send(command)
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
            self._tell(e)
            return self._leave()
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
            self.finished = not e.get("error")  # one that failed stays, to be read
        if kind in ("hello", "progress"):
            return self._tell(e)
        self._tell(e, keep=True)  # user, ask, turn, notice, and whatever a bridge adds
        self._leave()

    def _side(self, e):
        """One event of a side chat: kept with that chat, apart from the run's conversation, which
        (its state, what the dashboard shows of it) knows nothing of it. Caller holds `lock`."""
        sid, kind = str(e["side"]), e["type"]
        if sid not in self.sides:  # one a resumed run still has, replayed by its bridge
            if not sid.isdigit() or kind == "status":
                return
            self.sides[sid] = {"id": sid, "title": "", "state": "idle", "events": []}
            self.sided = max(self.sided, int(sid))
        side = self.sides[sid]
        if kind in ("delta", "text", "tool", "result"):
            fold(e, side["events"], *self.side_maps.setdefault(sid, ({}, {})))
        elif kind == "status":
            side["state"] = e["state"] if e.get("state") in STATES else "idle"
        elif kind != "progress":
            if kind == "user":
                side["title"] = side["title"] or " ".join(str(e.get("text")).split())[:80]
            side["events"].append(e)
            del side["events"][:-EVENTS]
        self._tell(e)

    def side(self, sid, text, close=False):
        """A question for a side chat (a new one without `sid`), or the end of one. Says which."""
        with lock:
            if close:
                if self.sides.pop(str(sid), None) is None:
                    raise ValueError("no such side chat")
                self.side_maps.pop(str(sid), None)
                if self.ready and self.exit is None:
                    self._send({"type": "side", "id": str(sid), "close": True})
                self._tell({"type": "side-closed", "side": str(sid)})
                return str(sid)
            if self.exit is not None:
                raise ValueError("this session has ended: resume it to go on")
            if not (self.ready and self.info.get("sides")):
                raise ValueError("this agent takes no side chats" if self.ready else "the agent is not ready yet")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("a question is text")
            if sid is None:
                self.sided += 1
                sid = self.sided
            elif str(sid) not in self.sides:
                raise ValueError("no such side chat")
            sid = str(sid)
            self._side({"type": "user", "side": sid, "text": text})
            self._side({"type": "status", "side": sid, "state": "working"})
            self._send({"type": "side", "id": sid, "text": text})
            return sid

    def _leave(self):
        """A session a plugin started (`once`) goes when its agent has finished: its turn over,
        nothing of it running in the background, nothing asked. Caller holds `lock`."""
        if self.once and self.finished and self.state == "idle" and not self.tasks and self.id in sessions:
            self.once = False
            threading.Thread(target=remove, args=(self,), daemon=True).start()  # never under its own pump

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
            self.finished = False
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
            elif self.exit is None and command.get("type") in ("model", "effort"):  # the last pick wins
                self.pending[command["type"]] = command
                self.info[command["type"]] = command.get("id", command.get("level"))

    def snapshot(self):
        """Everything a page needs to draw the session from nothing. Caller holds `lock`."""
        return {"type": "snapshot", "events": self.events, "info": self.info, "todos": self.todos, "tasks": self.tasks,
                "sides": list(self.sides.values()), "ready": self.ready, "status": self.status(), "session": self.json()}

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

    def shown(self):
        status = self.status()
        return "working" if status == "idle" and self.tasks else status  # what it started in the background runs on

    def json(self):
        return {**super().json(), "title": self.title, "activity": self.activity, "said": self.said,
                "agent": self.info.get("agent"), "model": self.info.get("model"), "cost": self.cost,
                "context": self.context, "waiting": len(self.waiting), "todos": self.todos}


def describe(project, keep=False):
    """What the project's enabled plugins have for the page: `run.sh --web` for the project, as a
    session would be run. The page draws it without knowing which plugin said what. With
    `keep`, a failure leaves the last description standing instead of replacing it."""
    try:
        done = subprocess.run([str(RUN_SH), "--web", "--project", project], cwd=Path.home(), capture_output=True,
                              text=True, timeout=120)
        if done.returncode:  # run.sh's own complaint, e.g. about the project's file
            raise ValueError(done.stderr.strip().splitlines()[-1] if done.stderr.strip() else "run.sh --web failed")
        found = json.loads(done.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        if keep and project in described:
            return described[project]
        found = {"lists": [], "notes": [str(e)]}
    described[project] = found
    autostart(project, found)
    return found


def on_status(last):
    """Runs each project's plugins' web_on_status commands for every session whose status, as the
    page shows it, changed since `last` (id → status, updated here); not for one first seen."""
    runs = []
    with lock:
        for s in sessions.values():
            status, before = s.shown(), last.get(s.id, "unseen")
            last[s.id] = status
            commands = described.get(s.project, {}).get("on_status") or {}
            if before in ("unseen", status) or not isinstance(commands, dict):
                continue
            page = f"{page_origin}/{'chat' if s.ui == 'chat' else 'session'}#{s.id}" if page_origin else ""
            event = json.dumps({"project": s.project, "run_id": s.run_id, "session": s.id, "url": page,
                                "status": status, "before": before})
            runs += [(plugin, command, event) for plugin, command in commands.items() if isinstance(command, list)]
        for gone in last.keys() - sessions.keys():
            del last[gone]
    for run in runs:
        threading.Thread(target=run_on_status, args=run, daemon=True).start()


def run_on_status(plugin, command, event):
    try:
        done = subprocess.run(command, input=event, capture_output=True, text=True, timeout=60, cwd=Path.home())
        if done.returncode:
            print(f"  {plugin}'s web_on_status exited with {done.returncode}: {done.stderr.strip()[-300:]}",
                  file=sys.stderr, flush=True)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"  {plugin}'s web_on_status failed: {e}", file=sys.stderr, flush=True)


def status_watcher():
    last = {}
    while True:
        on_status(last)
        time.sleep(1)


IDLE_POLL = 300  # seconds between descriptions of a project none of whose plugins asked for any


def poller(projects_file):
    """Describes each project again whenever the shortest interval its plugins registered
    (web_poll) has passed, page or no page: what they watch — a pull request's CI turning
    green — is noticed, and what they want started on it (web_start) starts."""
    due = {}
    while True:
        for project in projects(projects_file):
            if time.time() >= due.get(project, 0):
                poll = describe(project, keep=True).get("poll")
                due[project] = time.time() + (max(10, poll) if isinstance(poll, (int, float)) else IDLE_POLL)
        time.sleep(5)


def agent_offers(offer=None, project=None):
    """What each project's agent last offered on `ready` (models, efforts, commands), kept in a file
    so a new chat shows it while its sandbox still starts, after a restart too. With `offer`, this
    is now the project's. shortcut: per project, so a run whose settings pick another agent shows
    the project's usual agent's offer until its own `ready`."""
    file = STATE.parent / "offers.json"
    try:
        known = json.loads(file.read_text())
        known = known if isinstance(known, dict) else {}
    except (OSError, ValueError):
        known = {}
    if offer is not None and known.get(project) != offer:
        known[project] = offer
        try:
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(json.dumps(known))
        except OSError:
            pass  # not kept: the next chat waits for its agent's `ready`, as it always did
    return known


def autostart(project, found):
    """Starts the sessions the project's plugins asked for (web_start): each `key` of a plugin
    once, kept in a file so a restart starts none again, and none while a session of its
    `after_run` is listed. Such a session is removed when its agent has finished (Chat._leave)."""
    file = STATE.parent / "started.json"
    for want in found.get("starts") or []:
        try:
            plugin, key, task = str(want["plugin"]), str(want["key"]), want["task"]
            sets = {str(k): str(v) for k, v in (want.get("env") or {}).items()}
        except (TypeError, KeyError, AttributeError):
            continue
        mark = f"{project}\t{plugin}\t{key}"
        with lock:
            if want.get("after_run") and any((s.project, s.run_id) == (project, want["after_run"]) for s in sessions.values()):
                continue
            try:
                seen = json.loads(file.read_text())
            except (OSError, ValueError):
                seen = []
            if mark in seen:
                continue
            try:
                start(project, "run", None, task, sets={**sets, "SANDBOX_STARTED_BY": plugin}, once=True)
                # shortcut: the file only grows, a line per session ever started; prune it once that matters.
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(json.dumps([*seen, mark]))
            except (ValueError, OSError) as e:
                print(f"  {plugin} could not start a session in {project}: {e}", file=sys.stderr, flush=True)


def _manifest(path):
    try:
        found = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(found, dict):
        return None
    try:
        entries = auth.load(os.environ)
        problem = ""
    except Die as e:
        entries, problem = {}, str(e)
    found["settings"] = [offered(s, entries, problem) for s in found.get("settings") or [] if isinstance(s, dict)]
    return found


def offered(spec, entries, problem=""):
    """A setting as the page draws and the server checks it: one of type "auth" becomes the choice
    of the configured authentications of its type(s) — names only, never what they hold."""
    if spec.get("type") == "auth":
        types = [spec.get("auth")] if isinstance(spec.get("auth"), str) else list(spec.get("auth") or [])
        choices = sorted(n for n, e in entries.items() if e.get("type") in types)
        note = problem or ("" if choices else f"None of type {' or '.join(types)} in {auth.auth_file(os.environ)} yet.")
        return {**{k: v for k, v in spec.items() if k not in ("auth", "fills")}, "type": "enum", "choices": choices,
                "authTypes": types,
                "description": " ".join(filter(None, [spec.get("description"), note]))}
    if isinstance(spec.get("items"), dict):
        spec = {**spec, "items": offered(spec["items"], entries, problem)}
    if isinstance(spec.get("fields"), list):
        spec = {**spec, "fields": [offered(f, entries, problem) for f in spec["fields"]]}
    return spec


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
    """A project's file: what it holds now ({} without one), and where it is."""
    path = config_file(project)
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
    if not isinstance(config.get("repo", ""), str):
        raise ValueError(".repo must be a path on this machine or a git URL, or empty for none")
    plugins = config.get("plugins", {})
    if not isinstance(plugins, dict):
        raise ValueError(".plugins must be an object keyed by plugin name")
    for name, section in plugins.items():
        if not isinstance(section, dict):
            raise ValueError(f".plugins[\"{name}\"] must be an object")
        if section.get("enabled", True) not in (True, False, 0, 1):
            raise ValueError(f".plugins[\"{name}\"].enabled must be true or false")
    agents = config.get("agents", {})
    if not isinstance(agents, dict) or not all(isinstance(v, dict) for v in agents.values()):
        raise ValueError(".agents must be an object of objects keyed by agent name")
    # What the kernel, the agents and the plugins declare is checked against its declared type;
    # anything else is left to run.sh and the plugins, as before.
    owners = [((), config, kernel_manifest()["settings"])]
    owners += [(("agents", a["name"]), agents.get(a["name"], {}), a["settings"]) for a in agent_manifests()]
    owners += [(("plugins", p["name"]), plugins.get(p["name"], {}), p["settings"]) for p in plugin_manifests()]
    for where, section, settings in owners:
        for spec in settings:
            if "key" in spec and spec["key"] in section:
                path = (f'.{where[0]}["{where[1]}"]' if where else "") + f'.{spec["key"]}'
                check_setting(spec, section[spec["key"]], path)


def check_setting(spec, value, where):
    """One value against the type its owner declared for it (see README, "Declaring settings")."""
    kind = spec.get("type", "string")
    if value is None:
        raise ValueError(f"{where} must not be null: leave it out instead")
    if spec.get("authTypes") and value not in spec.get("choices", []):  # an authentication (offered())
        raise ValueError(f"{where}: no {' or '.join(spec['authTypes'])} called '{value}' in "
                         f"{auth.auth_file(os.environ)} (there: {', '.join(spec['choices']) or 'none'})")
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
    """Replaces the project's file in one step, so run.sh never reads half a file."""
    check_config(config)
    write_json(config_file(project), config)


def write_json(path, data, mode=None):
    """Replaces `path` in one step; it keeps its mode (`mode` when given, else 644 for a new one)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        try:
            os.chmod(tmp, mode or path.stat().st_mode & 0o777)
        except FileNotFoundError:
            os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def add_project(name, repo):
    """A new project: its file, naming its repo, or none (an empty repo in the container)."""
    if not isinstance(name, str) or not re.fullmatch(r"\w[\w.-]*", name):
        raise ValueError("a project's name is letters, digits, '.', '-' and '_', not starting with '.' or '-'")
    if config_file(name).exists():
        raise ValueError(f"there is a project '{name}' already")
    config = {} if repo is None or (isinstance(repo, str) and not repo.strip()) else {"repo": repo}
    check_config(config)
    write_json(config_file(name), config)


def delete_project(name):
    """A project's file goes; refused while a session of it is listed, which would be left without one."""
    with lock:
        if any(s.project == name for s in sessions.values()):
            raise ValueError(f"'{name}' still has sessions: delete them first")
    config_file(name).unlink()
    described.pop(name, None)


# What GET /api/auth shows for a secret (auth.SECRETS) that is set; POSTed back, it keeps the saved value.
MASKED = "(saved, not shown)"


def stored_auth():
    """Your authentications as they are in their file ({} without one). Unlike auth.load, a file
    others may read is taken too: saving it here makes it yours alone."""
    path = auth.auth_file(os.environ)
    try:
        entries = json.loads(path.read_text())
    except FileNotFoundError:
        entries = {}
    except (OSError, ValueError) as e:
        raise ValueError(f"{path} is not valid JSON ({e}): fix it by hand first")
    if not isinstance(entries, dict):
        raise ValueError(f"{path} must hold a JSON object: fix it by hand first")
    return entries


def read_auth():
    """Your authentications with every secret masked, and what each type holds. Keys and tokens are
    only ever written here, never read back: whoever reaches the API does not get them."""
    path = auth.auth_file(os.environ)
    entries = {name: {k: MASKED if k in auth.SECRETS and v not in (None, "") else v for k, v in e.items()}
               if isinstance(e, dict) else e for name, e in stored_auth().items()}
    return {"file": str(path), "exists": path.exists(), "config": entries,
            "types": {t: {"required": list(r), "optional": list(o)} for t, (r, o) in auth.TYPES.items()}}


def write_auth(entries):
    """Replaces the authentications' file, readable by you alone, once each entry is a complete one of its type."""
    if not isinstance(entries, dict):
        raise ValueError("the authentications must be a JSON object of entries keyed by name")
    stored = None
    for name, e in entries.items():
        if not isinstance(e, dict) or e.get("type") not in auth.TYPES:
            raise ValueError(f"{name}: .type must be one of {', '.join(auth.TYPES)}")
        for k in auth.SECRETS:  # left as read_auth showed it: the value saved under this name
            if e.get(k) == MASKED:
                stored = stored_auth() if stored is None else stored
                saved = stored.get(name) if isinstance(stored.get(name), dict) else {}
                if saved.get(k) in (None, "", MASKED):
                    raise ValueError(f"{name}: no {k} saved under this name (renamed?): enter it again")
                e[k] = saved[k]
        try:
            auth.entry(os.environ, name, e["type"], entries)
        except Die as err:
            raise ValueError(str(err)) from None
    write_json(auth.auth_file(os.environ), entries, 0o600)


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
            done = subprocess.run([str(RUN_SH), "--project", s.project, "--web-action", str(act["plugin"]),
                                   str(act["action"]), str(act.get("arg", ""))], cwd=Path.home(), capture_output=True,
                                  text=True, timeout=120)
            if done.returncode:
                said = done.stderr.strip()
                failed.append(f"{item.get('ref') or item.get('title')}: "
                              + (said.splitlines()[-1] if said else "run.sh --web-action failed"))
        except (OSError, KeyError, subprocess.TimeoutExpired) as e:
            failed.append(f"{item.get('ref') or item.get('title')}: {e}")
    return failed


def live_items(project, run_id):
    """What the project's plugins publish for a run while it runs (web_live_items: its demo
    server), read afresh: it changes faster than the project is described."""
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


def plugin_command(project, run_id, plugin, name):
    """What a plugin's page code asks of a run (web_command): the plugin's command run in the run's
    checkout, the run named in WEB_RUN_ID, and the JSON it prints. None when the project's plugin has
    no such command, the run has no checkout here, or the command failed. The checkout is the agent's:
    a command must not run git (or anything that reads its files as config) in it on this machine."""
    command = described.get(project, {}).get("commands", {}).get(plugin, {}).get(name)
    root = checkout(project, run_id)
    if not command or not root:
        return None
    try:
        return json.loads(subprocess.run(command, cwd=root, env={**os.environ, "WEB_RUN_ID": run_id},
                                         capture_output=True, text=True, timeout=20).stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


servers_lock = threading.Lock()
servers = {}  # plugin → (process, path of the unix socket it listens on): its web_server, running


def plugin_server(plugin):
    """The socket of a plugin's own HTTP server (web_server), started on first use: one for every
    project, as the first project described with it says to start it."""
    command = next((d["servers"][plugin] for d in list(described.values())
                    if isinstance(d.get("servers"), dict) and plugin in d["servers"]), None)
    if not command:
        raise ValueError(f"no project here has a server of the plugin {plugin}")
    with servers_lock:
        proc, path = servers.get(plugin, (None, None))
        if proc is None or proc.poll() is not None:
            if proc:  # it died: its socket and log go with it
                shutil.rmtree(os.path.dirname(os.path.dirname(path)), ignore_errors=True)
            # What a plugin serves may be a shell on your account (VS Code is). A socket in a 0700
            # directory keeps other local users out, and the only way in for a browser is
            # Handler.tunnel, behind the same guard as the terminals: it needs no login of its own.
            run_dir = tempfile.mkdtemp(prefix=f"sandbox-{plugin}-")
            # The socket in a directory of its own, which the server may hand a container (VS Code's
            # is one): what it plants there must not reach the log, nor be followed (connect()).
            os.mkdir(run_dir + "/socket")
            path = run_dir + "/socket/socket"
            with open(run_dir + "/log", "wb") as log:
                proc = subprocess.Popen(
                    command, env={**os.environ, "WEB_SOCKET": path, "WEB_BASE": f"/plugins/{plugin}"},
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                    start_new_session=True)  # a group of its own, to stop its children with it
            servers[plugin] = (proc, path)
        for _ in range(1800):  # the first request would otherwise come before it listens; a first
            # start may build an image first (VS Code's), hence the minutes
            if proc.poll() is not None:
                said = Path(os.path.dirname(os.path.dirname(path)), "log").read_text(errors="replace").strip()
                raise ValueError(f"{plugin}'s server exited with {proc.returncode}"
                                 + (f": {said.splitlines()[-1]}" if said else ""))
            if os.path.exists(path):
                return path
            time.sleep(0.1)
        raise ValueError(f"{plugin}'s server did not start listening")


def connect(path):
    """A connection to the unix socket at path, never to what a symlink there points at: a plugin's
    server may run in a container (VS Code's does), and a link it swaps in (to this machine's
    docker.sock, say) must not be reached as you. Through an O_PATH descriptor of the file itself."""
    fd = os.open(path, os.O_PATH | os.O_NOFOLLOW)
    up = socket.socket(socket.AF_UNIX)
    try:
        if not stat.S_ISSOCK(os.fstat(fd).st_mode):
            raise OSError(f"{path}: not a socket")
        up.connect(f"/proc/self/fd/{fd}")
    except OSError:
        up.close()
        raise
    finally:
        os.close(fd)
    return up


scoped = []


def hold(folder, mode, argv, cwd):
    """Starts a session's process under src/server/holder.py, which outlives this server. Under systemd
    it goes into a scope of its own: restarting this server's unit stops everything in its cgroup.
    The scope comes from the manager this server runs under: the user's, or the system's for a system unit."""
    if not scoped:
        units = [["systemd-run", *user, "--scope", "--quiet", "--collect", "--"] for user in (["--user"], [])]
        under = os.environ.get("INVOCATION_ID") and shutil.which("systemd-run")
        ok = next((u for u in units if under and subprocess.run(u + ["true"], capture_output=True).returncode == 0), [])
        if under and not ok:
            print("  no systemd scope for sessions: a restart of this unit stops them all"
                  " (give its unit KillMode=process)", file=sys.stderr, flush=True)
        scoped.append(ok)
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
        if s.kind == "shell":  # a shell on this machine, from before there were none: ended, not taken back
            remove(s)


def drop(s):
    """Forget a session. Caller holds `lock`. A live one is stopped first, and what it holds let
    go of by its pump once it has ended, never under it."""
    if sessions.pop(s.id, None) and s.exit is not None:
        s.close()


def remove(s):
    """Stops a session and forgets it: a deleted one, with nothing of its run tidied up."""
    s.stop()
    with lock:
        drop(s)


def sync(bind="127.0.0.1"):
    """Pulls main into this checkout and runs install.sh; then, under systemd, restarts this server,
    listening where this one does (`bind`)."""
    root = ROOT
    install = [str(root / "install.sh"), "--yes"] + ([] if bind in ("127.0.0.1", "localhost") else ["--bind", bind])
    for step in (["git", "-C", str(root), "pull", "--ff-only", "origin", "main"], install):
        done = subprocess.run(step, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if done.returncode:
            raise ValueError(f"{' '.join(step[:4])} failed:\n" + (done.stderr or done.stdout)[-2000:])
    if not os.environ.get("INVOCATION_ID"):  # systemd sets it in the services it starts
        return {"restarting": False}
    # Detached and a moment late, so this reply gets out before the restart takes the server down.
    subprocess.Popen(["sh", "-c", f"sleep 1; systemctl --user restart {SERVICE} || systemctl restart {SERVICE}"],
                     start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"restarting": True}


signing_in = {}  # agent → its sign-in command under way, waiting for its code
sign_in_lock = threading.Lock()


def _agent_command(agent, key, what):
    """The command an agent declares under `key` in its agent.json, its program found on this server."""
    meta = _manifest(AGENTS / agent / "agent.json") if re.fullmatch(r"[\w-]+", agent or "") else None
    command = (meta or {}).get(key)
    if not (isinstance(command, list) and command and all(isinstance(c, str) for c in command)):
        raise ValueError(f"agent {agent!r} has no {what}")
    # Installers put CLIs in ~/.local/bin, which a service's PATH may lack.
    exe = shutil.which(command[0]) or shutil.which(command[0], path=str(Path.home() / ".local/bin"))
    if not exe:
        raise ValueError(f"{command[0]} is not installed on the server (not on its PATH, nor in ~/.local/bin)")
    return [exe, *command[1:]]


def signed_in(agent):
    """Whether an agent's CLI on the server is signed in: its `signedIn` command (agent.json) exits 0."""
    command = _agent_command(agent, "signedIn", "sign-in check")
    try:
        return subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ValueError(f"cannot check the sign-in: {e}")


def sign_in(agent):
    """Starts the sign-in command an agent declares (`signIn` in its agent.json), dropping one of it
    still under way, and gives the link it prints: the page to sign in at, which ends on a code."""
    command = _agent_command(agent, "signIn", "sign-in")
    with sign_in_lock:
        if (old := signing_in.pop(agent, None)) and old.poll() is None:
            old.kill()
        try:
            proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, env={**os.environ, "BROWSER": "true"})
        except OSError as e:
            raise ValueError(f"cannot run {command[0]}: {e}")
        signing_in[agent] = proc
        out = ""
        # shortcut: waits for as long as it prints no link and does not exit; add a timeout if one ever hangs.
        while line := proc.stdout.readline():  # the link may be wrapped in an OSC 8 hyperlink
            out += line
            if m := re.search(r"https?://[^\s\x07\x1b]+", line):
                return m[0]
        proc.wait()
        raise ValueError(f"{' '.join(command)} gave no link:\n{out[-2000:]}")


def sign_in_code(agent, code):
    """Hands an agent's sign-in under way the code its page showed; it signs in with it, or says why not."""
    if not isinstance(code, str) or not code.strip():
        raise ValueError("no code")
    with sign_in_lock:
        proc = signing_in.pop(agent, None)
    if proc is None or proc.poll() is not None:
        raise ValueError("no sign-in under way: start it again")
    try:
        out, _ = proc.communicate(code.strip() + "\n", timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise ValueError("the sign-in did not finish")
    if proc.returncode:
        raise ValueError(out.rsplit(">", 1)[-1].strip() or "the sign-in failed")
    # The agent's own follow-up, its after-sign-in.sh: Claude's hands the new login to the sessions running.
    if (after := AGENTS / agent / "after-sign-in.sh").is_file():
        try:  # signed in all the same, whatever comes of it
            subprocess.run(["sh", str(after)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=60, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass


def start(project, kind, run_id, task=None, ui=None, images=None, sets=None, once=False):
    """A new session, or the live one it would double. An agent's session is a chat unless
    `ui` is "terminal" (its own TUI in a pty, as `run.sh` in your terminal)."""
    if ui not in (None, "chat", "terminal"):
        raise ValueError("ui must be chat or terminal")
    images = pictures(images)
    if (task is not None or images) and (kind != "run" or not isinstance(task or "", str) or not ((task or "").strip() or images)):
        raise ValueError("a task starts a new run, and is text")
    if images and ui == "terminal":
        raise ValueError("a terminal takes no images")
    if kind == "run":
        run_id = secrets.token_hex(3)
    elif kind != "resume" or not RUN_ID.fullmatch(run_id or ""):
        raise ValueError("kind must be run, or resume with a 6-hex-char run_id")
    with lock:
        title = ""
        for s in list(sessions.values()):
            if (s.project, s.run_id) != (project, run_id):
                continue
            # Two containers on one branch would push over each other: hand back the live one.
            # An ended one stays (its tab shows how it ended) until the next one of its run replaces it:
            # a run is one session however often it is resumed, and a resumed chat replays it.
            if s.exit is None:
                return s
            title = title or getattr(s, "title", "")
            drop(s)
        s = (Session if ui == "terminal" else Chat)(
            project, kind, run_id, task, **({"images": images} if images else {}), sets=sets, once=once)
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
        # rebinding, the Origin check stops cross-site requests. Any port: a proxy (a sandbox's
        # published port) may put this server on another, and the name is what rebinding forges.
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        # https too: behind a TLS proxy (serve-oauth.sh) the page is https://<Host>, the same site.
        if host.rsplit(":", 1)[0] in self.server.hosts and origin in (None, f"http://{host}", f"https://{host}"):
            global page_origin
            page_origin = origin or f"{self.headers.get('X-Forwarded-Proto', 'http')}://{host}"
            return True
        print(f"forbidden: Host={host!r} Origin={self.headers.get('Origin')!r} {self.command} {self.path}", file=sys.stderr, flush=True)
        self.reply(403, {"error": "forbidden"})
        return False

    def session(self, sid):
        with lock:
            s = sessions.get(sid)
        if s is None:
            self.reply(404, {"error": "no such session"})
        return s

    def tunnel(self, plugin):
        """Pass one request under /plugins/<plugin>/ to that plugin's server, and its answer back, as
        raw bytes: that carries its WebSockets too, and puts it on our origin and behind our guard."""
        if not self.guard():
            return
        try:
            up = connect(plugin_server(plugin))
        except (ValueError, OSError) as e:
            return self.reply(502, {"error": str(e)})
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
                    up.shutdown(socket.SHUT_RDWR)  # the browser hung up: so does the server's side
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
        m = re.match(r"/plugins/([\w-]+)(?:[/?]|$)", self.path)
        self.tunnel(m[1]) if m else mine()

    def do_GET(self):
        self.route(self.get)

    def do_POST(self):
        self.route(self.post)

    def do_PUT(self):  # nothing of ours, but a plugin's server may use any method
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
        elif m := re.fullmatch(r"/api/agents/([\w-]+)/signed-in", url.path):
            try:
                self.reply(200, {"signedIn": signed_in(m[1])})
            except ValueError as e:
                self.reply(400, {"error": str(e)})
        elif m := re.fullmatch(r"/api/agents/([\w-]+)/sign-in", url.path):  # a link to follow: on to its sign-in page
            try:
                target = sign_in(m[1])
            except ValueError as e:
                return self.reply(400, {"error": str(e)})
            self.send_response(302)
            self.send_header("Location", target)
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif url.path == "/api/auth":
            try:
                self.reply(200, read_auth())
            except ValueError as e:
                self.reply(400, {"error": str(e)})
        elif m := re.fullmatch(r"/api/sessions/(\w+)/offers", url.path):
            # What its page asks about before deleting it, one yes/no each.
            # Described afresh first: the pull request a run opened a moment ago is offered too,
            # and one closed or merged since is not.
            if s := self.session(m[1]):
                describe(s.project, keep=True)
                with lock:
                    found = offers(s)
                self.reply(200, {"offers": [{k: i.get(k) for k in ("url", "ref", "title")}
                                            | {"ask": str(i["on_delete"].get("ask") or f"Tidy up {i.get('ref') or i.get('title')} too?")}
                                            for i in found]})
        elif m := re.fullmatch(r"/api/sessions/(\w+)/plugins/([\w-]+)/([\w-]+)", url.path):
            if s := self.session(m[1]):
                self.reply(200, {"result": plugin_command(s.project, s.run_id, m[2], m[3])})
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
            elif url.path == "/api/auth":
                write_auth(json.loads(body).get("config"))
                self.reply(200, read_auth())
            elif url.path == "/api/projects":
                req = json.loads(body)
                add_project(req.get("name"), req.get("repo"))
                self.reply(200, {})
            elif url.path == "/api/projects/delete":
                req = json.loads(body)
                if req.get("name") not in projects(self.server.projects_file):
                    raise ValueError("not a configured project")
                delete_project(req["name"])
                self.reply(200, {})
            elif m := re.fullmatch(r"/api/agents/([\w-]+)/sign-in", url.path):
                sign_in_code(m[1], json.loads(body).get("code"))
                self.reply(200, {})
            elif url.path == "/api/sync":
                self.reply(200, sync(self.server.bind))
            elif m := re.fullmatch(r"/api/sessions/(\w+)/(prompt|interrupt|answer|model|effort|task|side)", url.path):
                s = self.session(m[1])
                if s is None:
                    return
                if s.ui != "chat":
                    raise ValueError("a terminal takes keystrokes, not prompts")
                req = json.loads(body) if body.strip() else {}
                if not isinstance(req, dict):
                    raise ValueError("the request must be a JSON object")
                if m[2] == "side":
                    return self.reply(200, {"id": s.side(req.get("id"), req.get("text"), bool(req.get("close")))})
                if m[2] == "prompt":
                    s.prompt(req.get("text"), req.get("images"), req.get("files"))
                else:  # only the fields a bridge reads, under the name the path gave
                    s.tell({"type": m[2], **{k: req[k] for k in ("id", "answers", "cancel", "level", "side") if k in req}})
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


def web_bind(bind):
    """The address the page listens on, as an address: a plugin publishing what a session serves
    (dev-server's demo container) publishes it there by default, so its links work from wherever the page was opened."""
    if bind and not re.fullmatch(r"[0-9.]+|.*:.*", bind):
        bind = socket.gethostbyname(bind)  # a name, e.g. a VPN's
    return bind or "0.0.0.0"


def serve(port, projects_file, bind="127.0.0.1", allow_hosts=()):
    # Loopback by default: there is no login, so anyone who can reach the port can start
    # sandboxes as you. --bind 0.0.0.0 opens it to your network; the Host allowlist still
    # names only this machine's own addresses (plus any --allow-host), so DNS rebinding stays blocked.
    server = ThreadingHTTPServer((bind, port), Handler)
    server.daemon_threads = True
    port = server.server_address[1]
    server.hosts = local_names(bind) | set(allow_hosts)
    server.projects_file = projects_file
    os.environ["SANDBOX_PROJECTS_DIR"] = str(projects_file)  # for read_config, and every run.sh it starts
    server.bind = bind
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
                        help="directory with a <name>.json per project (default: %(default)s)")
    args = parser.parse_args()
    # For every run.sh this starts, sessions and --web alike.
    os.environ["SANDBOX_WEB_BIND"] = web_bind(args.bind)
    if args.bind and os.environ["SANDBOX_WEB_BIND"] != args.bind:
        os.environ["SANDBOX_WEB_NAME"] = args.bind  # a name resolved to its address: links may keep the name
    restore()
    threading.Thread(target=poller, args=(args.projects,), daemon=True).start()
    threading.Thread(target=status_watcher, daemon=True).start()
    server = serve(args.port, args.projects, args.bind, args.allow_host)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # so `finally` cleans up on a plain kill too
    print(f"Sandboxes: http://127.0.0.1:{server.server_address[1]}  (projects: {args.projects})",
          flush=True)
    if args.bind not in ("127.0.0.1", "localhost"):
        print("  also on: " + ", ".join(sorted(f"{h}:{server.server_address[1]}" for h in server.hosts
                                               if not h.startswith(("127.", "localhost")))),
              "  (no login: anyone who can reach it can start sandboxes as you)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        with lock:  # they run on: what the next server takes them back from
            for s in list(sessions.values()):
                s.save()
        for proc, path in servers.values():
            try:  # what it spawned may outlive it (the `code` CLI leaves its server running)
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            shutil.rmtree(os.path.dirname(os.path.dirname(path)), ignore_errors=True)
