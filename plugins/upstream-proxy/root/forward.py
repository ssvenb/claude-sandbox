#!/usr/bin/env python3
"""The container half of upstream-proxy, in one of two modes.

Usage: forward.py --log FILE <port>=<socket> [<port>=<socket>]...
       forward.py --log FILE --attest DIR

Forwarding: ordinary HTTP clients need a TCP port, the host proxy listens on a unix socket, so each
bind-mounted socket is bridged to a loopback port — for this sandbox's processes only. Each
connection is traced back to its owner: the client end shows up in /proc/net/tcp with a socket
inode, and that inode must be an open fd of a process in this container's PID namespace.

Attesting (host-network): the container shares the HOST's loopback with every other sandbox on the
machine, so the project's shared host proxy listens on the ports itself — a forwarder here would
die with this container and take the port away from the project's other sandboxes. What only this
container can tell is whether a connection's client end is one of its own processes; the host
proxy asks every attestor of its project over a unix socket in DIR, and refuses a connection none
of them vouches for. Other projects' sandboxes, and the host's own processes, have no attestor
there, so they get a 403.

Runs as root so the agent cannot replace it. Binds before detaching, so a port that cannot be
bound fails the container's start.
"""

from __future__ import annotations

import argparse
import os
import secrets
import selectors
import socket
import sys
import threading
import time

sys.path.insert(0, "/usr/local/lib/sandbox")
from peer_owner import LOOPBACK, from_this_sandbox  # noqa: E402  (installed by the Dockerfile)
REFUSAL = (
    b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\n"
    b"This port belongs to another sandbox's upstream-proxy; use the endpoints in your own briefing.\n"
)


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


def bridge(client: socket.socket, upstream: socket.socket) -> None:
    other = threading.Thread(target=pump, args=(upstream, client), daemon=True)
    other.start()
    pump(client, upstream)
    other.join()
    client.close()
    upstream.close()


def attest(lsock: socket.socket) -> None:
    """Answer the host proxy, one `<peer port> <local port>` question per connection: 1 if a process
    of this sandbox holds the client end of that loopback connection, else 0. Sequential, because
    from_this_sandbox switches the process-wide euid."""
    while True:
        try:
            conn, _ = lsock.accept()
        except OSError:
            continue
        with conn:
            conn.settimeout(2)
            try:
                peer_port, local_port = map(int, conn.makefile("rb").readline(64).split())
                ok = from_this_sandbox(peer_port, local_port)
                conn.sendall(b"1\n" if ok else b"0\n")
            except (OSError, ValueError):
                continue
            if not ok:
                log(f"not ours: :{local_port} ← 127.0.0.1:{peer_port}")


def serve(listeners: dict[socket.socket, tuple[int, str]]) -> None:
    sel = selectors.DefaultSelector()
    for lsock in listeners:
        sel.register(lsock, selectors.EVENT_READ)
    while True:
        for key, _ in sel.select():
            port, sock_path = listeners[key.fileobj]
            try:
                client, (_, peer_port) = key.fileobj.accept()
            except OSError:
                continue
            if not from_this_sandbox(peer_port, port):
                log(f"refused :{port} ← 127.0.0.1:{peer_port}: not a process of this sandbox")
                try:
                    client.sendall(REFUSAL)
                except OSError:
                    pass
                client.close()
                continue
            upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                upstream.connect(sock_path)
            except OSError as e:
                log(f":{port} → {sock_path}: {e}")
                upstream.close()
                client.close()
                continue
            threading.Thread(target=bridge, args=(client, upstream), daemon=True).start()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--attest", metavar="DIR", help="vouch for this sandbox's connections in DIR")
    ap.add_argument("routes", nargs="*", metavar="PORT=SOCKET")
    args = ap.parse_args()
    if bool(args.attest) == bool(args.routes):
        ap.error("pass either --attest DIR or PORT=SOCKET routes")

    attestor = None
    if args.attest:
        # Every sandbox of the project shares DIR, so the name only has to be unique; the host
        # proxy drops the socket once nothing answers on it any more.
        path = os.path.join(args.attest, f"{os.environ.get('RUN_ID', 'sandbox')}-{secrets.token_hex(4)}.sock")
        attestor = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        attestor.bind(path)
        # The host proxy connects as the host user; a question answers nothing the asker could abuse.
        os.chmod(path, 0o666)
        attestor.listen(16)

    listeners: dict[socket.socket, tuple[int, str]] = {}
    for route in args.routes:
        port_s, _, sock_path = route.partition("=")
        port = int(port_s)
        lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # REUSEADDR only gets past TIME_WAIT leftovers; on Linux it never lets a second listener
        # share the port. REUSEPORT would, and is deliberately not set.
        lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            lsock.bind((LOOPBACK, port))
        except OSError as e:
            print(f"upstream-proxy: cannot listen on 127.0.0.1:{port}: {e.strerror}. Something else "
                  "in this container already holds the port — give this route another one.",
                  file=sys.stderr)
            return 1
        lsock.listen(128)
        listeners[lsock] = (port, sock_path)

    if os.fork():
        return 0
    os.setsid()
    out = os.open(args.log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    os.dup2(out, 1)
    os.dup2(out, 2)
    if attestor:
        attest(attestor)
    else:
        serve(listeners)
    return 0


if __name__ == "__main__":
    sys.exit(main())
