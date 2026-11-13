"""plugins/upstream-proxy/root/forward.py: the container half of upstream-proxy."""
import socket
import sys
import threading

import pytest

from conftest import load

forward = load("plugins/upstream-proxy/root/forward.py")


def unix_echo(path):
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(str(path))
    srv.listen()

    def loop():
        while True:
            conn, _ = srv.accept()
            with conn:
                while data := conn.recv(1024):
                    conn.sendall(data)
    threading.Thread(target=loop, daemon=True).start()
    return srv


def recv_all(sock):
    chunks = []
    while data := sock.recv(4096):
        chunks.append(data)
    return b"".join(chunks)


def start_serve(monkeypatch, sock_path, ours=True):
    monkeypatch.setattr(forward, "from_this_sandbox", lambda peer, local: ours)
    lsock = socket.socket()
    lsock.bind(("127.0.0.1", 0))
    lsock.listen()
    port = lsock.getsockname()[1]
    threading.Thread(target=forward.serve, args=({lsock: (port, str(sock_path))},), daemon=True).start()
    return port


def test_bridge_relays_both_ways_and_closes():
    client, client_far = socket.socketpair()
    upstream, upstream_far = socket.socketpair()
    t = threading.Thread(target=forward.bridge, args=(client_far, upstream_far))
    t.start()
    client.sendall(b"request")
    assert upstream.recv(100) == b"request"
    upstream.sendall(b"response")
    upstream.shutdown(socket.SHUT_WR)
    assert client.recv(100) == b"response"
    client.shutdown(socket.SHUT_WR)
    t.join(5)
    assert not t.is_alive()


def test_own_connections_are_bridged_to_the_socket(monkeypatch, short_tmp):
    unix_echo(short_tmp / "r.sock")
    port = start_serve(monkeypatch, short_tmp / "r.sock")
    with socket.create_connection(("127.0.0.1", port), timeout=5) as c:
        c.sendall(b"ping")
        c.shutdown(socket.SHUT_WR)
        assert recv_all(c) == b"ping"


def test_foreign_connections_get_a_403(monkeypatch, short_tmp):
    unix_echo(short_tmp / "r.sock")
    port = start_serve(monkeypatch, short_tmp / "r.sock", ours=False)
    with socket.create_connection(("127.0.0.1", port), timeout=5) as c:
        assert recv_all(c) == forward.REFUSAL


def test_missing_host_socket_drops_the_connection(monkeypatch, short_tmp):
    port = start_serve(monkeypatch, short_tmp / "absent.sock")
    with socket.create_connection(("127.0.0.1", port), timeout=5) as c:
        assert recv_all(c) == b""


@pytest.mark.parametrize("argv", [["--log", "x"], ["1=s"]], ids=["no routes", "no log"])
def test_needs_a_log_and_routes(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["forward.py", *argv])
    with pytest.raises(SystemExit) as exc:
        forward.main()
    assert exc.value.code == 2


def test_a_taken_port_fails_the_start(monkeypatch, capsys, short_tmp):
    taken = socket.socket()
    taken.bind(("127.0.0.1", 0))
    taken.listen()
    port = taken.getsockname()[1]
    monkeypatch.setattr(sys, "argv", ["forward.py", "--log", str(short_tmp / "log"), f"{port}=/x.sock"])
    assert forward.main() == 1
    assert f"cannot listen on 127.0.0.1:{port}" in capsys.readouterr().err
    taken.close()
