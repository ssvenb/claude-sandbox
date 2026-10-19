#!/usr/bin/env python3
"""Bridge each bind-mounted proxy socket to a loopback TCP port, for this sandbox's processes only.

Usage: forward.py --log FILE <port>=<socket> [<port>=<socket>]...

The container half of upstream-proxy: ordinary HTTP clients need a TCP port, the host proxy listens
on a unix socket. Under host-network the container shares the HOST's loopback, so a plain bridge
(socat) would hand every other sandbox on the machine this one's credentials. Each connection is
therefore traced back to its owner — the client end shows up in /proc/net/tcp with a socket inode,
and that inode must be an open fd of a process in this container's PID namespace. Other sandboxes'
processes, and the host's, are not visible here, so their connections are refused.

Runs as root so the agent cannot replace a forwarder. Binds every port before detaching, so a port
another sandbox already holds fails the container's start instead of silently routing this agent's
traffic to someone else's listener.
"""

from __future__ import annotations

import argparse
import os
import selectors
import socket
import struct
import sys
import threading
import time

LOOPBACK = "127.0.0.1"
V4_MAPPED_LOOPBACK = "::ffff:127.0.0.1"
REFUSAL = (
    b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\n"
    b"This port belongs to another sandbox's upstream-proxy; use the endpoints in your own briefing.\n"
)


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def _addr(hexaddr: str) -> tuple[str, int]:
    """Decode a /proc/net/tcp{,6} address: 32-bit words in host byte order, then a hex port."""
    host, port = hexaddr.split(":")
    raw = b"".join(struct.pack("=I", int(host[i:i + 8], 16)) for i in range(0, len(host), 8))
    family = socket.AF_INET if len(raw) == 4 else socket.AF_INET6
    return socket.inet_ntop(family, raw), int(port, 16)


def peer_inode(peer_port: int, local_port: int) -> int | None:
    """Socket inode of the client end of a loopback connection to local_port from peer_port."""
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(table) as f:
                next(f)
                for line in f:
                    fields = line.split()
                    (lhost, lport), (rhost, rport) = _addr(fields[1]), _addr(fields[2])
                    if (lport, rport) == (peer_port, local_port) \
                            and lhost in (LOOPBACK, V4_MAPPED_LOOPBACK) \
                            and rhost in (LOOPBACK, V4_MAPPED_LOOPBACK):
                        return int(fields[9]) or None
        except FileNotFoundError:
            continue
    return None


def _ids(pid: str) -> tuple[int, int] | None:
    """(uid, gid) of a process whose real, effective and saved ids all agree, else None."""
    uid = gid = None
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("Uid:"):
                    uid = set(line.split()[1:4])
                elif line.startswith("Gid:"):
                    gid = set(line.split()[1:4])
    except OSError:
        return None
    if not uid or not gid or len(uid) != 1 or len(gid) != 1:
        return None
    return int(uid.pop()), int(gid.pop())


def owned_here(inode: int) -> bool:
    """Whether a process in this PID namespace holds socket `inode` open.

    Reading another user's /proc/<pid>/fd needs CAP_SYS_PTRACE, which the container does not have;
    a matching fsuid/fsgid does instead. So each process is inspected as its own owner, switching
    euid/egid (which drive fsuid/fsgid) per owner and back to root afterwards. This is
    process-wide, so only the single accept loop ever calls it, and the bridge threads it spawns
    never touch the filesystem.
    """
    target = f"socket:[{inode}]"
    me = str(os.getpid())
    by_owner: dict[tuple[int, int], list[str]] = {}
    for pid in os.listdir("/proc"):
        if pid.isdigit() and pid != me and (ids := _ids(pid)):
            by_owner.setdefault(ids, []).append(pid)
    for (uid, gid), pids in by_owner.items():
        try:
            os.setegid(gid)
            os.seteuid(uid)
            for pid in pids:
                try:
                    fds = os.listdir(f"/proc/{pid}/fd")
                except OSError:
                    continue
                for fd in fds:
                    try:
                        if os.readlink(f"/proc/{pid}/fd/{fd}") == target:
                            return True
                    except OSError:
                        continue
        finally:
            os.seteuid(0)
            os.setegid(0)
    return False


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
            inode = peer_inode(peer_port, port)
            if inode is None or not owned_here(inode):
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
    ap.add_argument("routes", nargs="+", metavar="PORT=SOCKET")
    args = ap.parse_args()

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
            print(f"upstream-proxy: cannot listen on 127.0.0.1:{port}: {e.strerror}. Under host-network "
                  "the port is shared with the host and every other sandbox — give this route a port "
                  "no other running sandbox uses.", file=sys.stderr)
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
    serve(listeners)
    return 0


if __name__ == "__main__":
    sys.exit(main())
