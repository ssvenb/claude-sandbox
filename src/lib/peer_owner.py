"""Whether a loopback TCP connection comes from a process of this sandbox.

Shared by the root-owned helpers that listen on loopback ports (upstream-proxy's forwarder,
gcp-auth's metadata server). Under host-network the container shares the HOST's loopback, so such a
port is in reach of every other sandbox on the machine and of the host itself. The client end of
each connection shows up in /proc/net/tcp with a socket inode, and only a process in this
container's PID namespace can be found holding it — other sandboxes' processes, and the host's,
are not visible here.

    from peer_owner import from_this_sandbox
    if not from_this_sandbox(client_port, listening_port): refuse()

Root only, and not thread-safe: owned_here switches the process-wide euid, so call it from one
thread at a time.
"""

from __future__ import annotations

import os
import socket
import struct

LOOPBACK = "127.0.0.1"
V4_MAPPED_LOOPBACK = "::ffff:127.0.0.1"


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


def from_this_sandbox(peer_port: int, local_port: int) -> bool:
    """Whether a process of this sandbox holds the client end of 127.0.0.1:peer_port → local_port."""
    inode = peer_inode(peer_port, local_port)
    return inode is not None and owned_here(inode)
