"""The ports plugin: root/publish-ports.py in the container, host/portd.py (the central proxy) and
host/lease.py (its lifecycle) on the host, and its host stage."""
import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

from conftest import REPO, load

publish = load("plugins/ports/root/publish-ports.py")
portd = load("plugins/ports/host/portd.py")
lease_py = load("plugins/ports/host/lease.py")
Ports, items_file = lease_py.Ports, lease_py.items_file


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
    assert portd.url_host("100.64.0.1", "box.vpn.example") == "box.vpn.example"  # the web UI's --bind name
    assert portd.url_host("0.0.0.0", "box.vpn.example") == "{host}"


# --- its lifecycle on the host ----------------------------------------------------------------

def ports_env(tmp, **env):
    return {"TMPDIR": str(tmp), **env}


def test_a_run_joins_the_central_proxy_and_the_last_one_out_stops_it(short_tmp, capsys):
    lease = Ports(ports_env(short_tmp, PORTS="3000  5173"), "abc123")
    args = lease.start()
    base = short_tmp / f"sandbox-ports-{os.getuid()}-127.0.0.1"
    assert args == ["-v", f"{base}/runs/abc123:/run/ports/sockets", "-e", "PORTS_BIND=127.0.0.1", "-e", "PORTS=3000 5173"]
    assert "🔌 Ports: 3000, 5173 published on 127.0.0.1" in capsys.readouterr().err
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


@pytest.mark.parametrize("name, bind, passed", [("box.vpn.example", None, "box.vpn.example"), ("-x; rm", None, ""),
                                                ("box.vpn.example", "127.0.0.2", "")])  # PORTS_BIND's own address
def test_the_proxy_names_its_links_by_the_web_uis_name_only_when_it_is_a_host_name(short_tmp, name, bind, passed):
    """SANDBOX_WEB_BIND/SANDBOX_WEB_NAME: where the web UI listens, and the name its --bind gave for it."""
    lease = Ports(ports_env(short_tmp, PORTS="3000", PORTS_BIND=bind, SANDBOX_WEB_BIND="127.0.0.1",
                            SANDBOX_WEB_NAME=name), "abc123")
    lease.start()
    try:
        base = short_tmp / f"sandbox-ports-{os.getuid()}-{bind or '127.0.0.1'}"
        cmdline = Path(f"/proc/{(base / 'portd.pid').read_text().strip()}/cmdline").read_bytes().split(b"\0")
        assert cmdline[cmdline.index(b"--name") + 1] == passed.encode()
    finally:
        lease.release()


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
    with pytest.raises(lease_py.Die, match=message):
        Ports(ports_env(short_tmp, **env), "abc123").start()


def test_without_configured_ports_a_run_opens_none(short_tmp, capsys):
    lease = Ports(ports_env(short_tmp), "abc123")
    assert lease.start() == []
    assert "none published" in capsys.readouterr().err
    lease.release()
    assert not (short_tmp / f"sandbox-ports-{os.getuid()}-127.0.0.1").exists()  # no proxy


def test_a_directory_that_is_not_yours_is_refused(short_tmp):
    (short_tmp / "elsewhere").mkdir()
    (short_tmp / f"sandbox-ports-{os.getuid()}-127.0.0.1").symlink_to(short_tmp / "elsewhere")
    with pytest.raises(lease_py.Die, match="is not yours"):
        Ports(ports_env(short_tmp, PORTS="3000"), "abc123").start()


def test_web_lists_the_proxys_items_as_live(short_tmp):
    assert items_file(ports_env(short_tmp, PORTS_BIND="0.0.0.0")) == \
        f"{short_tmp}/sandbox-ports-{os.getuid()}-0.0.0.0/items.json"


def test_the_proxy_listens_where_the_web_ui_does_unless_ports_bind_says_otherwise(short_tmp):
    assert lease_py.bind_of({}) == "127.0.0.1"  # a run started from a terminal
    assert lease_py.bind_of({"SANDBOX_WEB_BIND": "100.64.0.1"}) == "100.64.0.1"
    assert lease_py.bind_of({"SANDBOX_WEB_BIND": "100.64.0.1", "PORTS_BIND": "10.0.0.2"}) == "10.0.0.2"


def test_the_host_stage_joins_the_proxy_and_its_exit_hook_leaves(sb, short_tmp):
    """host.sh, sourced as run.sh sources it: the stage's shell stands for the run."""
    base = short_tmp / f"sandbox-ports-{os.getuid()}-127.0.0.1"
    run = sb.plugin("ports", PORTS="3000", TMPDIR=short_tmp).ok()
    assert run.mounts == [f"{base}/runs/abc123:/run/ports/sockets"]
    assert run.env == {"PORTS_BIND": "127.0.0.1", "PORTS": "3000"}
    # The shell is gone, its exit hook with it: so are the run's directory and the proxy.
    assert not (base / "runs/abc123").exists() and not (base / "portd.pid").exists()
    assert sb.plugin("ports", TMPDIR=short_tmp).ok().args == []  # nothing listed: nothing opened
    sb.plugin("ports", PORTS="3000,5173", TMPDIR=short_tmp).dies("PORTS must list port numbers")


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
