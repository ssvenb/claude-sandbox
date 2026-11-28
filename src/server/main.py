#!/usr/bin/env python3
"""Web UI to orchestrate sandboxes: a dashboard of the configured projects with their sessions and
whatever their enabled plugins have to show (`run.sh --web`: open pull requests and issues, say);
a chat page per session, each in its own tab; and what a
plugin serves itself (web_server: VS Code in the browser, say), on our origin under /plugins/<name>/.

Runs on the HOST, as you, next to run.sh — a session is `run.sh --project <name> --chat`: the agent behind its chat bridge (agents/<name>/chat.mjs), whose events (src/services/chat/chat-bridge.mjs)
come out of run.sh's stdout and go to the page as server-sent events, while prompts come back as
POSTs. The page is there from the first moment: what is typed while the sandbox still builds and
boots waits here and is handed to the agent the moment it is ready. There is no shell on this
machine: every session is a sandbox, and every session is a chat.

    src/server/main.py [--port 8787] [--bind 127.0.0.1] [--allow-host NAME]... [--projects DIR]

DIR holds a <name>.json per project (default ~/.config/claude-sandbox/projects), its settings and
the repo it works on, and is re-read on every request. Sessions outlive this process: each
runs under src/server/holder.py, which keeps its output while no server listens, and a server that starts
takes back the sessions the last one left (STATE), running or ended — a restart cuts nothing off.
"""
import argparse
import os
import re
import shutil
import signal
import socket
import subprocess
import threading
from pathlib import Path

import uvicorn
from api.app import app
from api.common import Conf
from front import Front

import server as core


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


class Server:
    """This server on its port: serve_forever() runs it (uvicorn) until shutdown(), from another
    thread. Loopback by default: there is no login, so anyone who can reach the port can start
    sandboxes as you. --bind 0.0.0.0 opens it to your network; the Host allowlist still names only
    this machine's own addresses (plus any --allow-host), so DNS rebinding stays blocked."""

    def __init__(self, port, projects_file, bind="127.0.0.1", allow_hosts=()):
        self.sock = socket.create_server((bind or "0.0.0.0", port))
        self.server_address = self.sock.getsockname()[:2]
        self.hosts = local_names(bind) | set(allow_hosts)
        self.projects_file, self.bind = projects_file, bind
        os.environ["SANDBOX_PROJECTS_DIR"] = str(projects_file)  # for read_config, and every run.sh it starts
        c = Conf(self.hosts, bool(os.environ.get("SANDBOX_WEB_SUBDOMAINS")), projects_file, bind)  # serve-oauth.sh's: it relays demos
        # A page's open event stream holds a shutdown up no longer than this.
        self.uvicorn = uvicorn.Server(uvicorn.Config(Front(app, c), log_level="warning", lifespan="off",
                                                     timeout_graceful_shutdown=1, ws="websockets-sansio"))
        self.done = threading.Event()

    def serve_forever(self):
        try:
            self.uvicorn.run(sockets=[self.sock])
        finally:
            self.done.set()

    def shutdown(self):
        self.uvicorn.should_exit = True
        self.done.wait(10)

    def server_close(self):
        self.sock.close()


serve = Server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--bind", default="127.0.0.1",
                        help="address to listen on; 0.0.0.0 for every interface (default: %(default)s)")
    parser.add_argument("--allow-host", action="append", default=[], metavar="NAME",
                        help="another name the page may be opened by, e.g. a VPN's DNS name; .DOMAIN for any under it (repeatable)")
    parser.add_argument("--projects", type=Path,
                        default=Path.home() / ".config/claude-sandbox/projects",
                        help="directory with a <name>.json per project (default: %(default)s)")
    args = parser.parse_args()
    # For every run.sh this starts, sessions and --web alike.
    os.environ["SANDBOX_WEB_BIND"] = web_bind(args.bind)
    if args.bind and os.environ["SANDBOX_WEB_BIND"] != args.bind:
        os.environ["SANDBOX_WEB_NAME"] = args.bind  # a name resolved to its address: links may keep the name
    core.restore()
    threading.Thread(target=core.poller, args=(args.projects,), daemon=True).start()
    threading.Thread(target=core.status_watcher, daemon=True).start()
    server = serve(args.port, args.projects, args.bind, args.allow_host)
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
        with core.lock:  # they run on: what the next server takes them back from
            for s in list(core.sessions.values()):
                s.save()
        for proc, path in core.servers.values():
            try:  # what it spawned may outlive it (the `code` CLI leaves its server running)
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            shutil.rmtree(os.path.dirname(os.path.dirname(path)), ignore_errors=True)
