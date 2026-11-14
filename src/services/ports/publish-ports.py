#!/usr/bin/env python3
"""The container half of published ports: offers the configured ports the agent's servers listen on.

Usage: publish-ports.py --log FILE --port PORT [--port PORT]... <dir>

Watches this container's /proc/net/tcp and tcp6 for listening sockets of any user but root (root
only runs the sandbox's own helpers: upstream-proxy's forwarder, gcp-auth's metadata server), and
for each such port the project configured (PORTS, the --port arguments) listens on
<dir>/<port>.sock, relaying every connection to the address the server listens on — 127.0.0.1 for a server on every address, so one bound to localhost only is
published just the same. A port no longer listened on is withdrawn.

<dir> is bind-mounted from the host, where the central port proxy (src/services/ports/portd.py) gives each
socket a TCP port on the host. It sits in a root-only directory: the agent cannot reach it to plant
anything there for the host to connect to (entrypoint.sh). Runs as root, detached; its own sockets are unix ones,
so it never shows up in what it watches.
"""
from __future__ import annotations

import argparse
import ipaddress
import os
import socket
import sys
import threading
import time

SCAN = 1.0  # seconds between looks at the listening sockets
LISTEN = "0A"  # TCP_LISTEN, as /proc/net/tcp spells a socket's state


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def address(hex_addr: str) -> str:
    """/proc/net/tcp's address (host byte order, 32-bit words) as text."""
    raw = bytes.fromhex(hex_addr)
    raw = b"".join(raw[i:i + 4][::-1] for i in range(0, len(raw), 4))
    ip = ipaddress.ip_address(raw)
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return str(ip)


def listening(tables=("/proc/net/tcp", "/proc/net/tcp6")) -> dict[int, str]:
    """port → address to reach it on, for every socket a non-root user listens on."""
    found: dict[int, str] = {}
    for table in tables:
        try:
            with open(table, encoding="ascii") as fh:
                rows = fh.read().splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            f = row.split()
            if len(f) < 8 or f[3] != LISTEN or f[7] == "0":
                continue
            hex_addr, hex_port = f[1].split(":")
            port, addr = int(hex_port, 16), address(hex_addr)
            # Every address: reached on loopback. IPv4 first, should both families listen.
            addr = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(addr, addr)
            if port not in found or ":" in found[port]:
                found[port] = addr
    return found


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


def relay(client: socket.socket, addr: str, port: int) -> None:
    try:
        up = socket.create_connection((addr, port), timeout=10)
        up.settimeout(None)
    except OSError as e:
        log(f":{port} → {addr}: {e}")
        client.close()
        return
    other = threading.Thread(target=pump, args=(up, client), daemon=True)
    other.start()
    pump(client, up)
    other.join()
    client.close()
    up.close()


class Offer:
    def __init__(self, path: str, addr: str, port: int):
        self.path, self.addr, self.port, self.closed = path, addr, port, False
        if os.path.lexists(path):
            os.unlink(path)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(path)
        os.chmod(path, 0o666)  # the host proxy connects as the host user
        self.sock.listen(64)
        self.sock.settimeout(1)
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self) -> None:
        while not self.closed:
            try:
                client, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                if self.closed:
                    break
                time.sleep(0.1)
                continue
            client.settimeout(None)
            threading.Thread(target=relay, args=(client, self.addr, self.port), daemon=True).start()

    def close(self) -> None:
        self.closed = True
        # shutdown first: a plain close leaves a thread blocked in accept() holding the socket.
        for stop in (lambda: self.sock.shutdown(socket.SHUT_RDWR), self.sock.close):
            try:
                stop()
            except OSError:
                pass
        try:
            os.unlink(self.path)
        except OSError:
            pass


def watch(directory: str, ports: set[int], once: bool = False) -> dict[int, Offer]:
    offers: dict[int, Offer] = {}
    while True:
        now = {p: a for p, a in listening().items() if p in ports}
        for port in [p for p, o in offers.items() if now.get(p) != o.addr]:
            offers.pop(port).close()
            log(f":{port} withdrawn")
        for port, addr in now.items():
            if port not in offers:
                try:
                    offers[port] = Offer(os.path.join(directory, f"{port}.sock"), addr, port)
                    log(f":{port} ({addr}) offered")
                except OSError as e:
                    log(f":{port}: {e}")
        if once:
            return offers
        time.sleep(SCAN)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--port", type=int, action="append", required=True, metavar="PORT",
                    help="a port to publish, when something listens on it; no others are")
    ap.add_argument("dir")
    args = ap.parse_args()
    # Whatever an earlier container of this run left behind is no longer served by anyone.
    for name in os.listdir(args.dir):
        if name.endswith(".sock"):
            os.unlink(os.path.join(args.dir, name))
    if os.fork():
        return 0
    os.setsid()
    out = os.open(args.log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    os.dup2(out, 1)
    os.dup2(out, 2)
    watch(args.dir, set(args.port))
    return 0


if __name__ == "__main__":
    sys.exit(main())
