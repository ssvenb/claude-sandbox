#!/usr/bin/env python3
"""Holds one web UI session's process, so that it outlives the server (a restart, an update).

    holder.py DIR -- ARGV...

Runs ARGV on pipes (a chat: stdout and stderr merged), in a session of its own, and keeps all it
prints in DIR/out. The server talks to it over DIR/sock in JSON lines. Its first line is
{"from": N}: the output from byte N on (negative: the last -N bytes), answered by {"from": M}
(where it really starts) and then {"o": base64} as it comes; then {"in": base64} and
{"eof": true} (closes its stdin) go the other way. Once the process has ended, a client is
told {"exit": code} after its output, and the holder leaves (DIR/exit has the code too) — not
before a client has heard it, so a server that was away when it ended still learns how.
"""
import base64
import json
import os
import queue
import select
import socket
import subprocess
import sys
import threading
from pathlib import Path


def main():
    folder, argv = Path(sys.argv[1]), sys.argv[3:]
    child = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             start_new_session=True)  # a group of its own, to stop as one
    pid, out_fd, in_fd = child.pid, child.stdout.fileno(), child.stdin.fileno()
    log = open(folder / "out", "a+b", buffering=0)
    (folder / "pid").write_text(str(pid))
    total = 0

    # Input goes through a thread: a big prompt (pictures) must not stop the output being read.
    inbox = queue.Queue()

    def feed():
        while (data := inbox.get()) is not None:
            try:
                while data:
                    data = data[os.write(in_fd, data):]
            except OSError:
                return
        os.close(in_fd)
    threading.Thread(target=feed, daemon=True).start()

    def since(n):
        if n < 0:
            n = max(0, total + n)
        log.seek(min(n, total))
        return min(n, total), log.read()

    server = socket.socket(socket.AF_UNIX)
    os.chdir(folder)  # a socket's path is at most 108 bytes: bound here by its name alone
    server.bind("sock")
    server.listen()
    clients = {}  # socket → [what it sent that is not a whole line yet, attached?]
    code = None

    def send(c, message):
        try:
            c.sendall(json.dumps(message).encode() + b"\n")
            return True
        except OSError:
            c.close()
            clients.pop(c, None)
            return False

    def told(c):
        """Once the process has ended, a client that has heard it all is done with, and so are we."""
        if code is not None and send(c, {"exit": code}):
            (folder / "sock").unlink(missing_ok=True)
            sys.exit(0)

    def attached():
        return [c for c, (_, on) in clients.items() if on]

    while True:
        ready, _, _ = select.select([server, *clients] + ([out_fd] if code is None else []), [], [])
        for r in ready:
            if r is out_fd:
                try:
                    data = os.read(out_fd, 65536)
                except OSError:
                    data = b""
                if not data:
                    code = os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1])
                    (folder / "exit").write_text(str(code))
                    inbox.put(None)
                    for c in attached():
                        told(c)
                    continue
                total += len(data)
                log.write(data)
                for c in attached():
                    send(c, {"o": base64.b64encode(data).decode()})
            elif r is server:
                clients[server.accept()[0]] = [b"", False]
            elif r in clients:
                try:
                    got = r.recv(1 << 20)
                except OSError:
                    got = b""
                if not got:
                    r.close()
                    del clients[r]
                    continue
                *lines, clients[r][0] = (clients[r][0] + got).split(b"\n")
                for line in lines:
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(msg, dict):
                        continue
                    if "from" in msg and not clients[r][1]:  # attach: what it missed, then live
                        start, data = since(int(msg["from"]))
                        clients[r][1] = True
                        if send(r, {"from": start}) and (not data or send(r, {"o": base64.b64encode(data).decode()})):
                            told(r)
                    elif "in" in msg and code is None:
                        inbox.put(base64.b64decode(msg["in"]))
                    elif msg.get("eof"):
                        inbox.put(None)
                    if r not in clients:  # a send to it failed
                        break

if __name__ == "__main__":
    main()
