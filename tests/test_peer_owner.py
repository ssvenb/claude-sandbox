"""src/shared/peer_owner.py: is a loopback connection's client end held by a process of this sandbox?

owned_here switches euid per process owner and back to root; unprivileged, the switch back would
fail, so the tests make it a no-op and only ever look at processes of the test's own user.
"""
import os
import socket
import struct
import subprocess
import sys

import pytest

import peer_owner


def proc_hex(host: str, port: int) -> str:
    """Encode an address the way /proc/net/tcp does: 32-bit words in host byte order."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    raw = socket.inet_pton(family, host)
    words = struct.unpack(f"={len(raw) // 4}I", raw)
    return "".join(f"{w:08X}" for w in words) + f":{port:04X}"


@pytest.mark.parametrize("host", ["127.0.0.1", "::ffff:127.0.0.1", "::1", "10.1.2.3"])
def test_addr_decodes_proc_net_tcp(host):
    assert peer_owner._addr(proc_hex(host, 8080)) == (host, 8080)


@pytest.fixture
def listener():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen()
    yield s
    s.close()


@pytest.fixture
def no_euid_switch(monkeypatch):
    monkeypatch.setattr(peer_owner.os, "seteuid", lambda uid: None)
    monkeypatch.setattr(peer_owner.os, "setegid", lambda gid: None)


def test_peer_inode_finds_the_client_end(listener):
    client = socket.create_connection(listener.getsockname())
    server_side, (_, peer_port) = listener.accept()
    try:
        inode = peer_owner.peer_inode(peer_port, listener.getsockname()[1])
        assert inode == os.fstat(client.fileno()).st_ino
        assert peer_owner.peer_inode(peer_port, 1) is None
    finally:
        client.close()
        server_side.close()


def test_ids_reads_a_process_owner():
    assert peer_owner._ids(str(os.getpid())) == (os.getuid(), os.getgid())
    assert peer_owner._ids("999999999") is None


def test_connection_held_by_another_local_process_is_ours(listener, no_euid_switch):
    host, port = listener.getsockname()
    child = subprocess.Popen(
        [sys.executable, "-c", f"import socket,sys; s=socket.create_connection(('{host}',{port})); "
                               "print('up', flush=True); sys.stdin.read()"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline() == "up\n"
        conn, (_, peer_port) = listener.accept()
        assert peer_owner.from_this_sandbox(peer_port, port)
        conn.close()
    finally:
        child.kill()
        child.wait()


def test_unknown_connection_or_inode_is_not_ours(no_euid_switch):
    assert not peer_owner.from_this_sandbox(1, 2)
    assert not peer_owner.owned_here(1)


def test_the_checking_process_itself_does_not_count(listener, no_euid_switch):
    """Only the helper itself would hold such a socket, never an agent process: it is skipped."""
    client = socket.create_connection(listener.getsockname())
    conn, (_, peer_port) = listener.accept()
    try:
        assert not peer_owner.from_this_sandbox(peer_port, listener.getsockname()[1])
    finally:
        client.close()
        conn.close()
