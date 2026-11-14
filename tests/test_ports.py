"""Published ports: src/services/ports/publish-ports.py in the container, src/services/ports/portd.py (the central proxy) and
src/services/ports/lease.py (its lifecycle) on the host."""
import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

from conftest import REPO, orchestrator, load
from services.ports.lease import Ports, items_file

publish = load("src/services/ports/publish-ports.py")
portd = load("src/services/ports/portd.py")


def echo_server(sock: socket.socket, prefix: bytes = b"") -> socket.socket:
    """Answers every connection with prefix + what it got, until the peer stops sending."""
    sock.listen(16)

    def serve():
        while True:
            try:
                conn, _ = sock.accept()
            except OSError:
                return
            with conn:
                data = b""
                while chunk := conn.recv(4096):
                    data += chunk
                conn.sendall(prefix + data)
    threading.Thread(target=serve, daemon=True).start()
    return sock


def tcp_echo(prefix: bytes = b"") -> socket.socket:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    return echo_server(s, prefix)


def unix_echo(path: Path, prefix: bytes = b"") -> socket.socket:
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(path))
    return echo_server(s, prefix)


def ask(conn: socket.socket, data: bytes = b"hi") -> bytes:
    with conn:
        conn.settimeout(5)
        conn.sendall(data)
        conn.shutdown(socket.SHUT_WR)
        got = b""
        while chunk := conn.recv(4096):
            got += chunk
        return got


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --- the container half ---------------------------------------------------------------------

def test_proc_net_addresses_are_read_in_host_byte_order():
    assert publish.address("0100007F") == "127.0.0.1"
    assert publish.address("00000000000000000000000001000000") == "::1"
    assert publish.address("0000000000000000FFFF00000100007F") == "127.0.0.1"  # v4-mapped


def test_listening_finds_what_non_root_users_listen_on(tmp_path):
    header = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
    (tmp_path / "tcp").write_text(header + "".join(
        f"   0: {local} 00000000:0000 {st} 00000000:00000000 00:00000000 00000000  {uid}        0 1 1\n"
        for local, st, uid in [
            ("00000000:0BB8", "0A", 1000),   # :3000 on every address
            ("0100007F:1F90", "0A", 1000),   # :8080 on localhost only
            ("0100007F:1F91", "0A", 0),      # :8081, root's: a sandbox helper
            ("0100007F:1F92", "01", 1000),   # :8082, an established connection
        ]))
    (tmp_path / "tcp6").write_text(header + "".join(
        f"   0: {local} 00000000000000000000000000000000:0000 0A 00000000:00000000 00:00000000 00000000  1000 0 1 1\n"
        for local in ["00000000000000000000000000000000:0BB8",    # :3000 again, IPv6
                      "00000000000000000000000001000000:1388"]))  # :5000 on ::1 only
    found = publish.listening((tmp_path / "tcp", tmp_path / "tcp6"))
    assert found == {3000: "127.0.0.1", 8080: "127.0.0.1", 5000: "::1"}


def test_a_port_listened_on_is_offered_as_a_socket_and_withdrawn_when_it_closes(tmp_path):
    server = tcp_echo(b"svc:")
    port = server.getsockname()[1]
    offers = publish.watch(str(tmp_path), {port}, once=True)
    assert offers[port].addr == "127.0.0.1"
    conn = socket.socket(socket.AF_UNIX)
    conn.connect(str(tmp_path / f"{port}.sock"))
    assert ask(conn) == b"svc:hi"
    assert (tmp_path / f"{port}.sock").stat().st_mode & 0o777 == 0o666  # the host user connects
    (tmp_path / "unlisted").mkdir()
    assert publish.watch(str(tmp_path / "unlisted"), set(), once=True) == {}  # only configured ports
    assert list((tmp_path / "unlisted").iterdir()) == []
    server.close()
    for offer in offers.values():
        offer.close()
    assert not (tmp_path / f"{port}.sock").exists()


# --- the central proxy ------------------------------------------------------------------------

@pytest.fixture
def daemon(short_tmp):
    for d in ("users", "runs"):
        (short_tmp / d).mkdir()
    d = portd.Daemon(str(short_tmp), "127.0.0.1")
    d.dir = short_tmp

    def run(run_id, pid=os.getpid()):
        (short_tmp / "users" / str(pid)).write_text(run_id + "\n")
        (short_tmp / "runs" / run_id).mkdir(exist_ok=True)
        return short_tmp / "runs" / run_id
    d.join = run
    yield d
    d.stop()


def test_each_session_gets_its_own_host_port_for_the_same_port(daemon):
    port = free_port()
    a, b = daemon.join("aaaaaa"), daemon.join("bbbbbb", os.getppid())
    servers = [unix_echo(a / f"{port}.sock", b"a:"), unix_echo(b / f"{port}.sock", b"b:")]
    assert daemon.scan()
    ports = json.loads((daemon.dir / "ports.json").read_text())
    by_run = {p["run_id"]: p["host_port"] for p in ports}
    # The same number for the first one seen, while it is free; another one for the second.
    assert sorted(by_run.values())[0] != 0 and port in by_run.values() and len(set(by_run.values())) == 2
    assert ask(socket.create_connection(("127.0.0.1", by_run["aaaaaa"]))) == b"a:hi"
    assert ask(socket.create_connection(("127.0.0.1", by_run["bbbbbb"]))) == b"b:hi"
    items = json.loads((daemon.dir / "items.json").read_text())
    assert {"run_id": "bbbbbb", "ref": f":{port}", "url": f"http://{{host}}:{by_run['bbbbbb']}/"}.items() \
        <= next(i for i in items if i["run_id"] == "bbbbbb").items()
    for s in servers:
        s.close()


def test_a_withdrawn_port_closes_and_comes_back_on_the_same_host_port(daemon):
    run = daemon.join("aaaaaa")
    first = unix_echo(run / "4000.sock")
    daemon.scan()
    [p] = json.loads((daemon.dir / "ports.json").read_text())
    first.close()
    (run / "4000.sock").unlink()
    daemon.scan()
    assert json.loads((daemon.dir / "ports.json").read_text()) == []
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", p["host_port"]), timeout=2).close()
    again = unix_echo(run / "4000.sock")
    daemon.scan()
    assert json.loads((daemon.dir / "ports.json").read_text()) == [p]  # the server restarted: same port
    again.close()


def test_only_sockets_of_live_runs_are_published(daemon, tmp_path):
    run = daemon.join("aaaaaa")
    elsewhere = unix_echo(tmp_path / "host.sock")
    (run / "5000.sock").symlink_to(tmp_path / "host.sock")  # planted: not followed
    (run / "5001.sock").write_text("")                      # not a socket
    gone = daemon.join("cccccc", pid=2 ** 22 + 1)            # its run.sh is dead
    dead = unix_echo(gone / "5002.sock")
    assert daemon.scan()
    assert json.loads((daemon.dir / "ports.json").read_text()) == []
    elsewhere.close()
    dead.close()


def test_the_proxy_exits_once_nobody_uses_it(daemon):
    daemon.join("aaaaaa", pid=2 ** 22 + 1)
    assert not daemon.scan()
    assert daemon.done()
    daemon.join("bbbbbb")
    assert not daemon.done()


def test_links_name_the_host_the_way_the_page_can_reach_it():
    assert portd.url_host("127.0.0.1") == "{host}"
    assert portd.url_host("0.0.0.0") == "{host}"
    assert portd.url_host("192.168.1.5") == "192.168.1.5"
    assert portd.url_host("fd00::1") == "[fd00::1]"


# --- its lifecycle on the host ----------------------------------------------------------------

def ports_env(tmp, **env):
    return {"TMPDIR": str(tmp), **env}


def test_a_run_joins_the_central_proxy_and_the_last_one_out_stops_it(short_tmp, capsys):
    lease = Ports(ports_env(short_tmp, PORTS="3000  5173"), "abc123")
    args = lease.start()
    base = short_tmp / f"sandbox-ports-{os.getuid()}-127.0.0.1"
    assert args == ["--add-host=host.docker.internal:host-gateway", "-v", f"{base}/runs/abc123:/run/ports/sockets",
                    "-e", "PORTS_BIND=127.0.0.1", "-e", "PORTS=3000 5173"]
    assert "🔌 Ports: 3000, 5173 published on 127.0.0.1" in capsys.readouterr().out
    assert (base / f"users/{os.getpid()}").read_text() == "abc123\n"
    assert os.listdir(base / "runs") == ["abc123"]
    pid = int((base / "portd.pid").read_text())
    for _ in range(50):
        if (base / "ports.json").exists():
            break
        time.sleep(0.1)
    lease.release()
    # The run's directory, and the proxy, are gone with the last run out.
    assert not (base / "runs/abc123").exists() and not (base / "portd.pid").exists()
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        try:  # our child: reap it, or it lingers as a zombie that kill(0) still finds
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            pass
        time.sleep(0.1)
    else:
        raise AssertionError("the proxy outlived its last user")


def test_a_second_run_shares_the_proxy_and_keeps_it_when_the_first_leaves(short_tmp):
    base = short_tmp / f"sandbox-ports-{os.getuid()}-127.0.0.1"
    other = subprocess.Popen(["sleep", "30"])
    try:
        base.joinpath("users").mkdir(parents=True)
        base.joinpath("runs/0a0a0a").mkdir(parents=True)
        base.joinpath("runs/dead00").mkdir(parents=True)  # its run.sh is gone: pruned on the way in
        (base / f"users/{other.pid}").write_text("0a0a0a\n")
        lease = Ports(ports_env(short_tmp, PORTS="3000"), "abc123")
        lease.start()
        assert not (base / "runs/dead00").exists()
        lease.release()
        assert (base / "runs/0a0a0a").is_dir() and (base / "portd.pid").exists()  # still in use
        assert not (base / "runs/abc123").exists()
    finally:
        other.kill()
        other.wait()
        pid = (base / "portd.pid").read_text().strip() if (base / "portd.pid").exists() else ""
        if pid:
            subprocess.run(["kill", pid])


@pytest.mark.parametrize("env, message", [({"PORTS_BIND": "localhost; rm"}, "PORTS_BIND must be an IP"),
                                          ({"PORTS": "3000,5173"}, "PORTS must list port numbers"),
                                          ({"PORTS": "70000"}, "PORTS must list port numbers")])
def test_settings_that_are_refused(short_tmp, env, message):
    with pytest.raises(orchestrator.Die, match=message):
        Ports(ports_env(short_tmp, **env), "abc123").start()


def test_without_configured_ports_a_run_opens_none(short_tmp, capsys):
    lease = Ports(ports_env(short_tmp), "abc123")
    assert lease.start() == ["--add-host=host.docker.internal:host-gateway"]  # the host is still reachable
    assert "none published" in capsys.readouterr().out
    lease.release()
    assert not (short_tmp / f"sandbox-ports-{os.getuid()}-127.0.0.1").exists()  # no proxy


def test_a_directory_that_is_not_yours_is_refused(short_tmp):
    (short_tmp / "elsewhere").mkdir()
    (short_tmp / f"sandbox-ports-{os.getuid()}-127.0.0.1").symlink_to(short_tmp / "elsewhere")
    with pytest.raises(orchestrator.Die, match="is not yours"):
        Ports(ports_env(short_tmp, PORTS="3000"), "abc123").start()


def test_web_lists_the_proxys_items_as_live(short_tmp):
    assert items_file(ports_env(short_tmp, PORTS_BIND="0.0.0.0")) == \
        f"{short_tmp}/sandbox-ports-{os.getuid()}-0.0.0.0/items.json"


# --- dev-server -------------------------------------------------------------------------------

def test_sandbox_server_starts_stops_and_restarts_the_command(tmp_path):
    tool = REPO / "plugins/dev-server/bin/sandbox-server"
    env = {**os.environ, "SANDBOX_SERVER_DIR": str(tmp_path), "SANDBOX_SERVER_LOG": str(tmp_path / "log"),
           "SANDBOX_SERVER_PID": str(tmp_path / "pid"),
           "DEV_SERVER_COMMAND": "pwd; sleep 30 & sleep 30"}

    def server(*args):
        return subprocess.run([tool, *args], env=env, capture_output=True, text=True, timeout=20)
    assert server("status").returncode == 3
    assert server("start").returncode == 0
    pid = int((tmp_path / "pid").read_text())
    assert "Already running" in server("start").stdout
    for _ in range(50):
        if str(tmp_path) in (tmp_path / "log").read_text():
            break
        time.sleep(0.1)
    assert str(tmp_path) in server("log").stdout  # ran in its directory
    assert server("restart").returncode == 0
    assert int((tmp_path / "pid").read_text()) != pid
    assert server("stop").stdout.strip() == "Stopped."
    # The whole session is gone, the backgrounded sleep included.
    assert subprocess.run(["pgrep", "-s", str(pid)], capture_output=True).returncode == 1


def test_sandbox_server_without_a_command_says_so(tmp_path):
    done = subprocess.run([REPO / "plugins/dev-server/bin/sandbox-server", "start"], capture_output=True, text=True,
                          env={"PATH": os.environ["PATH"], "SANDBOX_SERVER_PID": str(tmp_path / "pid")})
    assert done.returncode == 1 and "No server configured" in done.stderr
