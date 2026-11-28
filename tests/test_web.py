"""src/server/server.py: chats on pipes, streamed to the page; only our own page may drive it."""
import base64
import json
import os
import queue
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest
from pathlib import Path

from conftest import REPO

sys.path.insert(0, str(REPO / "src/server"))
import server as web  # noqa: E402

UI = REPO / "web"  # the pages: a React app, built into UI/dist, which the server serves


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    """Where sessions' holders keep their sockets and output: one place per test."""
    monkeypatch.setattr(web, "STATE", tmp_path / "state")
    return tmp_path / "state"


def build_ui():
    """Makes sure web/dist is there and no older than what it is built from: `npm run build`
    (after `npm ci`, without node_modules) when it is not. Without npm, a build that is there is
    used as it is, and with none the test is skipped. Returns dist."""
    dist = UI / "dist"
    sources = [f for f in (*(UI / "src").rglob("*"), *(UI / name for name in (
        "index.html", "package.json", "package-lock.json", "vite.config.ts", "tsconfig.json"))) if f.is_file()]
    built = (dist / "index.html").stat().st_mtime if (dist / "index.html").exists() else 0
    if built >= max(f.stat().st_mtime for f in sources):
        return dist
    if not shutil.which("npm"):
        if built:
            return dist  # stale, but all there is
        pytest.skip("the web UI is not built and there is no npm to build it: `npm ci && npm run build` in web")
    steps = ([] if (UI / "node_modules").exists() else [["npm", "ci"]]) + [["npm", "run", "build"]]
    for step in steps:
        done = subprocess.run(step, cwd=UI, capture_output=True, text=True)
        assert done.returncode == 0, f"{' '.join(step)} in web failed:\n{done.stdout}{done.stderr}"
    return dist


@pytest.fixture(scope="session")
def ui_dist():
    return build_ui()


def configured(tmp_path, monkeypatch, name="proj", repo=None):
    """A projects directory holding <name>.json, its repo `repo` (else tmp_path), for this test."""
    listing = tmp_path / "projects"
    listing.mkdir(exist_ok=True)
    (listing / f"{name}.json").write_text(json.dumps({"repo": str(repo or tmp_path)}))
    monkeypatch.setenv("SANDBOX_PROJECTS_DIR", str(listing))
    return listing


@pytest.fixture
def ui(tmp_path, ui_dist):
    project = tmp_path / "proj"
    project.mkdir()
    listing = tmp_path / "projects"
    listing.mkdir()
    (listing / "proj.json").write_text(json.dumps({"repo": str(project)}))
    proc = subprocess.Popen([sys.executable, REPO / "src/server/server.py", "--port", "0", "--projects", listing,
                             ], stdout=subprocess.PIPE, text=True,
                            env={"PATH": f"{tmp_path}/bin:/usr/bin:/bin", "SHELL": "/bin/sh", "HOME": str(tmp_path)})
    base = proc.stdout.readline().split()[1]

    def call(path, body=None, method=None, **headers):
        req = urllib.request.Request(base + path, data=body, headers={"Content-Type": "application/json", **headers}, method=method)
        try:
            return urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as e:
            return e
    call.project, call.tmp = "proj", tmp_path
    yield call
    for s in json.load(call("/api/state"))["sessions"]:  # they would outlive the server
        call(f"/api/sessions/{s['id']}", method="DELETE")
    for _ in range(100):  # each one's folder goes once it has ended
        if not any(tmp_path.glob(".local/state/claude-sandbox/sessions/*")):
            break
        time.sleep(0.05)
    proc.terminate()
    proc.wait(5)


def test_there_is_no_shell_on_this_machine(ui):
    # The server runs as you: a shell of its own would be your account, to anyone who reaches the page.
    assert ui("/api/sessions", json.dumps({"kind": "shell"}).encode()).status == 400
    assert json.load(ui("/api/state"))["sessions"] == []


def test_a_proxy_may_put_the_page_on_another_port(ui):
    assert ui("/", Host="127.0.0.1:45319").status == 200  # e.g. a sandbox's published port


def test_a_tls_proxy_puts_the_page_on_https(ui):
    # serve-oauth.sh: oauth2-proxy terminates TLS and passes the Host through.
    assert ui("/api/state", Host="127.0.0.1", Origin="https://127.0.0.1").status == 200
    assert ui("/api/state", Host="127.0.0.1", Origin="https://evil.example").status == 403


@pytest.mark.parametrize("body, headers, status", [
    ({"project": "/etc", "kind": "run"}, {}, 400),                         # not a configured project
    ({"kind": "resume", "run_id": "x; rm -rf"}, {}, 400),                  # not a run id
    ({"kind": "shell"}, {}, 400),                                          # no shell on this machine
    ({"kind": "run", "ui": "terminal"}, {}, 400),                          # no terminals: every session is a chat
    ({"kind": "run"}, {"Origin": "http://evil.example"}, 403),             # another site's page
    ({"kind": "run"}, {"Host": "evil.example"}, 403),                      # DNS rebinding
    ({"kind": "run"}, {"Host": "127.0.0.1:1", "Origin": "http://127.0.0.1:2"}, 403),  # another port's page
])
def test_requests_that_must_not_start_anything(ui, body, headers, status):
    body = {"project": ui.project, **body}
    assert ui("/api/sessions", json.dumps(body).encode(), **headers).status == status
    assert json.load(ui("/api/state"))["sessions"] == []


def test_sandbox_sessions_run_run_sh_under_an_id_the_ui_knows():
    run = [str(REPO / "run.sh"), "--project", "app"]
    assert web.command("app", "run", "0a1b2c") == [*run, "--run-id", "0a1b2c", "--chat"]  # a chat, its task its first prompt
    assert web.command("app", "resume", "0a1b2c") == [*run, "--resume", "0a1b2c", "--chat"]
    assert web.command("app", "run", "0a1b2c", {"GH_AUTH": "reviewer"})[-3:] == ["--chat", "--set", "GH_AUTH=reviewer"]
    for kind, run_id, task in (("resume", "0a1b2c", "x"), ("run", None, 7),
                               ("run", None, "  ")):
        with pytest.raises(ValueError, match="a task starts a new run"):
            web.start("/p", kind, run_id, task)


def test_the_projects_are_the_files_in_their_directory(tmp_path):
    listing = tmp_path / "projects"
    listing.mkdir()
    for name in ("beta", "alpha"):
        (listing / f"{name}.json").write_text("{}")
    (listing / ".alpha.json.x1").write_text("")  # a save in progress
    (listing / "notes.txt").write_text("")
    assert web.projects(listing) == ["alpha", "beta"]
    assert web.projects(tmp_path / "none") == []


def test_a_network_bind_admits_this_machines_own_names_only():
    names = web.local_names("0.0.0.0")
    assert {"127.0.0.1", "localhost", web.socket.gethostname()} <= names
    assert "evil.example" not in names
    assert web.local_names("127.0.0.1") == {"127.0.0.1", "localhost"}


def test_runs_learn_where_the_page_listens_as_an_address():
    assert web.web_bind("0.0.0.0") == "0.0.0.0"
    assert web.web_bind("") == "0.0.0.0"
    assert web.web_bind("192.168.1.5") == "192.168.1.5"
    assert web.web_bind("127.0.0.1") == "127.0.0.1"
    assert web.web_bind("localhost.") == "127.0.0.1"  # a name: its address


def test_allow_host_adds_a_name_to_the_allowlist(tmp_path):
    server = web.serve(0, tmp_path / "projects", allow_hosts=["box.vpn.example"])
    try:
        assert {"box.vpn.example", "127.0.0.1"} <= server.hosts
        assert "evil.example" not in server.hosts
    finally:
        server.server_close()


def test_an_allowed_dot_domain_takes_any_name_under_it():
    # A demo of this server, reached as <RUN_ID>-<port>.box.example.com through another's relay.
    assert web.allowed({".box.example.com"}, "0a1b2c-8790.box.example.com")
    assert not web.allowed({".box.example.com"}, "box.example.com.evil") and not web.allowed({".box.example.com"}, "xbox.example.com")
    assert web.allowed({"box.example.com"}, "0a1b2c-8790.box.example.com")  # a demo of it, behind its relay
    assert not web.allowed({"box.example.com"}, "x.box.example.com") and not web.allowed({"box.example.com"}, "0a1b2c-8790.evil.example")


def test_a_runs_published_port_is_a_subdomain_relayed_without_the_sign_ins_cookies(tmp_path, monkeypatch):
    app = socket.create_server(("127.0.0.1", 0))  # the demo's server: answers with the request it got

    def serve():
        while True:
            try:
                conn, _ = app.accept()
            except OSError:
                return
            with conn:
                head = b""
                while b"\r\n\r\n" not in head and (chunk := conn.recv(4096)):
                    head += chunk
                conn.sendall(b"HTTP/1.0 200 OK\r\n\r\n" + head)
    threading.Thread(target=serve, daemon=True).start()
    items = tmp_path / "items.json"  # as dev-server's host.sh writes them
    items.write_text(json.dumps([{"run_id": "0a1b2c", "port": 3000, "upstream": ["127.0.0.1", app.getsockname()[1]]}]))
    monkeypatch.setattr(web, "described", {"proj": {"live": [str(items)]}})
    monkeypatch.setenv("SANDBOX_WEB_SUBDOMAINS", "1")  # as serve-oauth.sh starts it
    server = web.serve(0, tmp_path / "projects", allow_hosts=["box.example.com"])
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.delenv("SANDBOX_WEB_SUBDOMAINS")
    demo = web.serve(0, tmp_path / "projects", allow_hosts=[".box.example.com"])  # this server as a demo
    threading.Thread(target=demo.serve_forever, daemon=True).start()

    def ask(host, cookie="a=1", to=server):
        with socket.create_connection(("127.0.0.1", to.server_address[1]), timeout=5) as c:
            c.sendall(f"GET /x?y=1 HTTP/1.1\r\nHost: {host}\r\nCookie: {cookie}\r\nConnection: close\r\n\r\n".encode())
            got = b""
            while chunk := c.recv(4096):
                got += chunk
            return got.decode()
    try:
        got = ask("0a1b2c-3000.box.example.com", "_oauth2_proxy=me; a=1; _oauth2_proxy_csrf=x; b=2")
        assert got.startswith("HTTP/1.1 200") and "GET /x?y=1 HTTP/1.1" in got
        assert "host: 0a1b2c-3000.box.example.com" in got.lower() and "Cookie: a=1; b=2" in got and "me" not in got
        assert "Cookie" not in ask("0a1b2c-3000.box.example.com:4180", "_oauth2_proxy=me")  # nothing else
        assert ask("0a1b2c-3001.box.example.com").startswith("HTTP/1.1 502")  # not published
        assert ask("0a1b2c-3000.evil.example").startswith("HTTP/1.1 403")  # not our name: our own guard's
        # Behind the relay, the demo answers the subdomain itself, rather than relaying it once more.
        got = ask("0a1b2c-3000.box.example.com", to=demo)
        assert "not published" not in got and "GET /x?y=1" not in got
    finally:
        for s in (server, demo):
            s.shutdown()
            s.server_close()
        app.close()


def test_the_pages_are_one_built_app_and_what_it_loads_is_served_under_its_own_path(ui):
    page = ui("/").read()
    assert b'<div id="root">' in page and ui("/").headers["Content-Type"].startswith("text/html")
    assert ui("/chat").read() == page  # the app picks the page by its path
    assert ui("/session").status == 404  # a terminal's page, gone with the terminals
    assert b"localStorage.getItem('theme')" in page  # the pinned day or night, set before the first paint
    scripts, styles = re.findall(rb'src="(/assets/[^"]+\.js)"', page), re.findall(rb'href="(/assets/[^"]+\.css)"', page)
    assert len(scripts) == 1 and styles
    script = ui(scripts[0].decode())
    assert script.status == 200 and script.headers["Content-Type"].startswith("text/javascript")
    code = script.read()
    assert b"/api/project" in code  # the dashboard; a session's page loads its own part, only where there is one
    assert b"Message to the agent" not in code  # the chat's composer
    [chunk] = [f.name for f in (UI / "dist/assets").glob("*.js") if b"Message to the agent" in f.read_bytes()]
    got = ui(f"/assets/{chunk}")
    assert got.status == 200 and got.headers["Content-Type"].startswith("text/javascript") and chunk.encode() in code
    assert not [f for f in (UI / "dist/assets").glob("*.js") if b"xterm" in f.read_bytes()]  # no terminal's xterm.js
    for style in styles:
        got = ui(style.decode())
        assert got.status == 200 and got.headers["Content-Type"].startswith("text/css")


@pytest.mark.parametrize("path", ["/server.py", "/../server.py", "/assets/../../server.py", "/../../run.sh", "/index.html",
                                  "/assets/nope.js", "/%2e%2e/server.py", "/assets", "/ui/package.json", "/package.json"])
def test_only_what_the_build_made_for_the_pages_is_served(ui, path):
    assert ui(path).status == 404


def test_without_a_build_the_pages_say_how_to_make_one(tmp_path):
    for part in ("src/server", "src/orchestrator"):  # the server, with the auth.py it reads authentications with
        shutil.copytree(REPO / part, tmp_path / part, ignore=shutil.ignore_patterns("__pycache__"))
    proc = subprocess.Popen([sys.executable, tmp_path / "src/server/server.py", "--port", "0", "--projects", tmp_path / "projects"],
                            stdout=subprocess.PIPE, text=True, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
    try:
        base = proc.stdout.readline().split()[1]
        for page in ("/", "/chat"):
            with pytest.raises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(base + page, timeout=10)
            assert e.value.code == 503 and e.value.headers["Content-Type"].startswith("text/plain")
            assert "npm ci && npm run build" in e.value.read().decode()
        assert json.load(urllib.request.urlopen(base + "/api/state", timeout=10))["sessions"] == []  # the API is there all the same
    finally:
        proc.terminate()
        proc.wait(5)


# Stands in for `docker`, whose `run` of VS Code's container serves on WEB_SOCKET: echoes each
# request's head back as the response body.
FAKE_DOCKER = r"""#!/usr/bin/env python3
import os, socket, sys
args = sys.argv[1:]
if args[0] != "run":
    sys.exit(0)  # build, rm
assert args[-1] == "--serve" and "-e" in args and "WEB_SOCKET" in args
s = socket.socket(socket.AF_UNIX)
s.bind(os.environ["WEB_SOCKET"])
s.listen()
while True:
    c, _ = s.accept()
    head = b""
    while b"\r\n\r\n" not in head:
        head += c.recv(65536)
    c.sendall(b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n" + head)
    c.close()
"""


def test_a_plugins_server_is_reached_on_its_socket_never_through_a_planted_link(tmp_path):
    real = socket.socket(socket.AF_UNIX)
    real.bind(str(tmp_path / "real"))
    real.listen()
    web.connect(str(tmp_path / "real")).close()
    (tmp_path / "planted").symlink_to(tmp_path / "real")  # this machine's docker.sock, say
    with pytest.raises(OSError):
        web.connect(str(tmp_path / "planted"))
    (tmp_path / "file").write_text("")
    with pytest.raises(OSError, match="not a socket"):
        web.connect(str(tmp_path / "file"))


def test_a_plugins_server_starts_on_first_use_behind_the_guarded_tunnel(ui):
    vscode = "/plugins/agent-workspace/"  # agent-workspace serves VS Code
    json.load(ui("/api/projects/" + ui.project))
    mirror = ui.tmp / ".agent-workspaces/proj-20261112-0a1b2c"
    mirror.mkdir(parents=True)
    # run.sh itself fails here (no App key), but the session keeps its run id, as an ended run does.
    s = json.load(ui("/api/sessions", json.dumps({"project": ui.project, "kind": "resume",
                                                  "run_id": "0a1b2c"}).encode()))
    assert s["workspace"] == str(mirror) and "agent-workspace" in s["plugins"]
    docker = ui.tmp / "bin/docker"
    docker.parent.mkdir()
    docker.write_text("#!/bin/sh\necho 'cannot build' >&2; exit 1\n")
    docker.chmod(0o755)
    failed = ui(vscode + "?folder=/x")
    assert failed.status == 502 and "docker" in json.load(failed)["error"]  # what the plugin said
    docker.write_text(FAKE_DOCKER)

    seen = ui(vscode + "?folder=/x").read()  # started afresh, the failed one gone
    assert seen.startswith(b"GET /plugins/agent-workspace/?folder=/x HTTP/1.1\r\n")  # its path as it came
    assert ui(vscode, b"body").read().startswith(b"POST /plugins/agent-workspace/ ")  # the same server again
    assert ui("/plugins/agent-workspace").read().startswith(b"GET /plugins/agent-workspace ")
    # What a plugin serves may be a shell on this machine: our own page only.
    assert ui(vscode, Origin="http://evil.example").status == 403
    assert ui(vscode, Host="evil.example").status == 403
    assert ui("/plugins/github-auth/").status == 502  # serves nothing
    assert ui("/pluginsx").status == 404


def test_a_plugins_websocket_and_requests_pass_the_tunnel_as_they_came_and_never_a_planted_link(tmp_path, monkeypatch):
    """VS Code in the browser lives on its WebSocket: through the tunnel it reaches the plugin's server
    with the browser's Host, path and subprotocol, both ways; a link planted where its socket was is
    never followed, and another site's page is refused before anything is relayed."""
    from websockets.sync.client import connect as ws
    from websockets.sync.server import unix_serve
    from websockets.exceptions import InvalidStatus

    def echo(conn):
        conn.send(json.dumps({"host": conn.request.headers["Host"], "path": conn.request.path}))
        for message in conn:
            conn.send(message)
    path = str(tmp_path / "socket")
    plugin = unix_serve(echo, path, subprotocols=["vscode"])
    threading.Thread(target=plugin.serve_forever, daemon=True).start()
    monkeypatch.setattr(web, "plugin_server", lambda name: path)
    call = api_server(tmp_path, monkeypatch)
    port = call.server.server_address[1]
    try:
        with ws(f"ws://127.0.0.1:{port}/plugins/agent-workspace/ws?t=1", subprotocols=["vscode"],
                origin=f"http://127.0.0.1:{port}") as c:
            assert json.loads(c.recv(timeout=5)) == {"host": f"127.0.0.1:{port}", "path": "/plugins/agent-workspace/ws?t=1"}
            assert c.subprotocol == "vscode"
            c.send("text")
            c.send(b"\x00bytes")
            assert (c.recv(timeout=5), c.recv(timeout=5)) == ("text", b"\x00bytes")
        with pytest.raises(InvalidStatus):  # another site's page
            ws(f"ws://127.0.0.1:{port}/plugins/agent-workspace/ws", origin="http://evil.example")
        os.rename(path, path + ".real")
        os.symlink(path + ".real", path)  # this machine's docker.sock, say
        with pytest.raises(InvalidStatus):
            ws(f"ws://127.0.0.1:{port}/plugins/agent-workspace/ws", origin=f"http://127.0.0.1:{port}")
        assert call("GET", "/plugins/agent-workspace/")[0] == 502  # nor a request
    finally:
        call.server.shutdown()
        plugin.shutdown()


def test_an_upload_through_the_tunnel_streams_to_the_plugins_server_as_it_comes(tmp_path, monkeypatch):
    """A big body (a file dropped into VS Code) is not held in memory until it is all there: the
    plugin's server has its first half while the browser still sends the second."""
    path, got, first = str(tmp_path / "socket"), bytearray(), threading.Event()
    plugin = socket.socket(socket.AF_UNIX)
    plugin.bind(path)
    plugin.listen()

    def serve():
        c, _ = plugin.accept()
        with c:
            head = b""
            while b"\r\n\r\n" not in head:
                head += c.recv(65536)
            head, _, body = head.partition(b"\r\n\r\n")
            got.extend(body)
            size = int(re.search(rb"(?i)content-length: *(\d+)", head)[1])
            while len(got) < size:
                if len(got) >= size // 2:
                    first.set()
                got.extend(c.recv(65536))
            c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
    threading.Thread(target=serve, daemon=True).start()
    monkeypatch.setattr(web, "plugin_server", lambda name: path)
    call = api_server(tmp_path, monkeypatch)
    half = b"x" * (1 << 20)
    try:
        with socket.create_connection(("127.0.0.1", call.server.server_address[1]), timeout=10) as c:
            c.sendall(b"PUT /plugins/agent-workspace/upload HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                      b"Content-Length: %d\r\nConnection: close\r\n\r\n" % (2 * len(half)) + half)
            assert first.wait(10), "the plugin's server saw nothing of it before it was all sent"
            c.sendall(half)
            answer = b""
            while chunk := c.recv(65536):
                answer += chunk
        assert answer.startswith(b"HTTP/1.1 200") and answer.endswith(b"ok") and bytes(got) == half * 2
    finally:
        call.server.shutdown()
        plugin.close()


def test_the_page_gets_what_the_projects_plugins_describe(ui):
    # No plugin of this bare directory has anything to list, but the answer is run.sh's own.
    said = json.load(ui("/api/projects/" + ui.project))
    assert said["lists"] == [] and said["agent"] == "claude" and "git-workspace" in said["plugins"]
    assert ui("/api/projects/etc").status == ui("/api/projects/%2Fetc").status == 404  # not a configured project


def test_a_projects_settings_are_read_and_saved_to_its_file(ui):
    file = ui.tmp / "projects/proj.json"
    put = lambda config, **headers: ui(f"/api/projects/{ui.project}/config", json.dumps(config).encode(),  # noqa: E731
                                       "PUT", **headers)
    got = json.load(ui(f"/api/projects/{ui.project}/config"))
    assert (got["file"], got["exists"], got["config"]) == (str(file), True, {"repo": str(ui.tmp / "proj")})
    kvm = next(p for p in got["plugins"] if p["name"] == "kvm")  # every plugin, as its manifest says
    assert kvm["defaultEnabled"] is False and kvm["description"] and "briefing" in kvm["example"]
    assert [s["key"] for s in kvm["settings"]] == ["briefing"]  # the settings it declares
    assert any(s["key"] == "agent" for s in got["kernel"]["settings"])  # and the sandbox's own
    claude = next(a for a in got["agents"] if a["name"] == "claude")
    assert any(s["key"] == "effort" for s in claude["settings"])

    config = {"repo": "https://github.com/o/r", "agent": "claude", "agents": {"claude": {"effort": "high"}},
              "plugins": {"kvm": {"enabled": True, "briefing": "VMs"}},
              "mine": [1]}  # whatever else the file holds is the page's to keep
    saved = json.load(put(config))
    assert saved["exists"] and saved["config"] == config == json.loads(file.read_text())
    assert file.read_text().endswith("}\n") and list((ui.tmp / "projects").iterdir()) == [file]

    for bad in ([], {"repo": 1}, {"plugins": []}, {"plugins": {"kvm": "on"}}, {"plugins": {"kvm": {"enabled": "maybe"}}},
                {"agents": []}, {"agents": {"claude": "high"}},
                # declared settings are checked against their type, wherever their owner keeps them
                {"agent": ["claude"]}, {"agents": {"claude": {"effort": "huge"}}},
                {"plugins": {"agent-workspace": {"cleanup": "yes"}}}, {"plugins": {"git-workspace": {"baseBranch": 1}}},
                {"plugins": {"dev-server": {"command": "make", "port": "80"}}}, {"plugins": {"project-setup": {"apt": "ripgrep"}}},
                {"plugins": {"dev-server": {"command": ["make"]}}},
                {"plugins": {"upstream-proxy": {"routes": [{"name": "a", "upstream": "https://x"}]}}},
                {"plugins": {"upstream-proxy": {"routes": [{"name": "a", "port": 70000, "upstream": "https://x"}]}}},
                {"plugins": {"upstream-proxy": {"routes": [{"name": "a", "port": 1, "upstream": "https://x",
                                                            "auth": {"type": "bearer", "credential": 7}}]}}}):
        bad = {"repo": "/r", **bad} if isinstance(bad, dict) and bad and "repo" not in bad else bad
        assert put(bad).status == 400
    assert json.loads(file.read_text()) == config  # none of them touched it
    assert ui("/api/projects/etc/config", b"{}", "PUT").status == ui("/api/projects/etc/config").status == 404
    assert ui(f"/api/projects/{ui.project}/config", b"{}").status == 405  # PUT, not POST
    assert put({}, Origin="http://evil.example").status == 403

    file.write_text("{not json")  # not ours to overwrite: fixed by hand first
    assert "not valid JSON" in json.load(ui(f"/api/projects/{ui.project}/config"))["error"]


def test_projects_are_added_and_deleted_and_authentications_saved_readable_by_you_alone(ui):
    post = lambda path, body, method=None: ui(path, json.dumps(body).encode(), method)  # noqa: E731
    assert post("/api/projects", {"name": "new", "repo": "~/code/new"}).status == 201
    assert json.loads((ui.tmp / "projects/new.json").read_text()) == {"repo": "~/code/new"}
    assert json.load(ui("/api/state"))["projects"] == ["new", ui.project]
    assert json.load(ui("/api/projects"))["projects"] == ["new", ui.project]
    assert post("/api/projects", {"name": "new", "repo": "/r"}).status == 409  # there is one of that name
    for bad in ({"name": "../x", "repo": "/r"}, {"name": ".x", "repo": "/r"}, {"name": "x", "repo": 1}):
        assert post("/api/projects", bad).status == 400
    assert post("/api/projects", {"name": "scratch", "repo": " "}).status == 201  # no repo: an empty one in the container
    assert json.loads((ui.tmp / "projects/scratch.json").read_text()) == {}
    assert ui("/api/projects/scratch", method="DELETE").status == 200
    assert ui("/api/projects/new", method="DELETE").status == 200
    assert ui("/api/projects/new", method="DELETE").status == 404  # not there any more
    assert json.load(ui("/api/state"))["projects"] == [ui.project]

    file = ui.tmp / ".config/claude-sandbox/auth.json"
    got = json.load(ui("/api/auth"))
    files = file.parent / "auth-files"
    assert (got["file"], got["exists"], got["config"], got["files"]) == (str(file), False, {}, {})
    assert "auth-files" not in json.dumps(got)  # where the files are is never shown
    assert got["types"]["github-app"] == {"required": ["appId", "privateKeyFile"], "optional": ["host", "username"]}
    entries = {"coder": {"type": "github-app", "appId": "1"}, "openai": {"type": "api-key", "key": "sk"}}
    masked = {"coder": entries["coder"], "openai": {"type": "api-key", "key": web.MASKED}}
    # A path is not saved: a file has its one place (auth.file_path), however the entry was sent.
    sent = {**entries, "coder": {**entries["coder"], "privateKeyFile": "~/k.pem"}}
    assert json.load(post("/api/auth", sent, "PUT"))["config"] == masked  # a secret is never sent back
    assert json.loads(file.read_text()) == entries and json.load(ui("/api/auth"))["config"] == masked
    assert file.stat().st_mode & 0o777 == 0o600
    assert post("/api/auth", masked, "PUT").status == 200  # left as shown: the saved key stays
    assert json.loads(file.read_text()) == entries
    assert post("/api/auth", {"renamed": masked["openai"]}, "PUT").status == 400  # none saved under that name
    for bad in ([], {"x": "y"}, {"x": {"type": "nope"}}, {"x": {"type": "api-key"}}, {"a b": {"type": "ssh-key"}}):
        assert post("/api/auth", bad, "PUT").status == 400
    assert json.loads(file.read_text()) == entries

    # A file is uploaded to its place under the entry's name, readable by you alone; and deleted.
    upload = lambda where, data: ui(f"/api/auth/{where}", data, "PUT")  # noqa: E731
    got = json.load(upload("coder/files/privateKeyFile", b"-----BEGIN KEY-----\n"))
    key = files / "coder/privateKey"
    told = {"kind": "Key", "size": 20, "modified": int(key.stat().st_mtime)}  # what it is, never its bytes
    assert got == {"exists": True, "file": told} and key.read_bytes() == b"-----BEGIN KEY-----\n"
    assert key.stat().st_mode & 0o777 == 0o600 and key.parent.stat().st_mode & 0o777 == files.stat().st_mode & 0o777 == 0o700
    assert json.load(ui("/api/auth"))["files"] == {"coder": {"privateKeyFile": told}}
    hosts = files / "coder/knownHosts"
    hosts.write_bytes(b"# mine\ngithub.com ssh-ed25519 AAAA\n\nexample.org ssh-rsa AAAA\n")
    assert json.load(ui("/api/auth"))["files"]["coder"]["knownHostsFile"]["kind"] == "2 hosts"
    hosts.unlink()
    for pem, kind in ((b"-----BEGIN OPENSSH PRIVATE KEY-----", "OpenSSH private key"),
                      (b"-----BEGIN RSA PRIVATE KEY-----", "RSA private key"), (b"ssh-rsa AAAA", "Not a PEM key")):
        key.write_bytes(pem)
        assert web.describe_file(key, "privateKeyFile")["kind"] == kind
    for data, kind in ((b'{"type": "service_account"}', "Service-account key"), (b"{", "Not JSON")):
        key.write_bytes(data)
        assert web.describe_file(key, "credentialFile")["kind"] == kind
    key.write_bytes(b"-----BEGIN KEY-----\n")
    for where, data in (("coder/files/appId", b"x"), ("%2E%2E/files/privateKeyFile", b"x"),
                        ("coder/files/privateKeyFile", b""), ("coder/files/privateKeyFile", b"x" * (web.MAX_AUTH_FILE + 1))):
        assert upload(where, data).status == 400
    assert upload("..%2Fx/files/privateKeyFile", b"x").status == 404  # a name has no "/": no such path
    assert not (file.parent / "x").exists() and key.read_bytes() == b"-----BEGIN KEY-----\n"
    assert json.load(ui("/api/auth/coder/files/privateKeyFile", method="DELETE"))["exists"] is False
    assert not key.exists() and json.load(ui("/api/auth"))["files"] == {}
    assert ui("/api/auth/coder/files/privateKeyFile", b"k", "PUT", Origin="http://evil.example").status == 403


def test_a_runs_checkout_is_found_where_a_plugin_says_it_is(tmp_path, monkeypatch):
    (tmp_path / "proj-20261112-0a1b2c").mkdir()
    monkeypatch.setitem(web.described, "/proj", {"checkout": f"{tmp_path}/*-{{run_id}}"})
    assert web.checkout("/proj", "0a1b2c") == str(tmp_path / "proj-20261112-0a1b2c")
    assert web.checkout("/proj", "ffffff") is None and web.checkout("/proj", None) is None
    assert web.checkout("/other", "0a1b2c") is None  # no plugin of that project keeps one


def test_a_plugins_command_runs_in_the_runs_checkout(tmp_path, monkeypatch):
    run = tmp_path / "proj-20261112-0a1b2c"
    run.mkdir()
    (run / "said").write_text('[{"path": "a.py"}]')
    monkeypatch.setitem(web.described, "/proj", {"checkout": f"{tmp_path}/*-{{run_id}}",
                                                 "commands": {"p": {"list": ["cat", "said"]}}})
    assert web.plugin_command("/proj", "0a1b2c", "p", "list") == [{"path": "a.py"}]
    assert web.plugin_command("/proj", "ffffff", "p", "list") is None  # no checkout of that run here
    assert web.plugin_command("/proj", "0a1b2c", "p", "other") is None  # no such command
    assert web.plugin_command("/proj", "0a1b2c", "q", "list") is None  # nor plugin
    (run / "said").write_text("not json")
    assert web.plugin_command("/proj", "0a1b2c", "p", "list") is None


def test_a_project_run_sh_cannot_describe_says_why(tmp_path, monkeypatch):
    configured(tmp_path, monkeypatch, "bad")
    (tmp_path / "projects/bad.json").write_text("{not json")
    [note] = web.describe("bad")["notes"]
    assert "bad.json" in note
    configured(tmp_path, monkeypatch, "gone", tmp_path / "gone")
    [note] = web.describe("gone")["notes"]
    assert "is not a directory" in note


def test_a_plugins_server_that_will_not_start_says_what_it_printed(tmp_path, monkeypatch):
    monkeypatch.setitem(web.described, "/proj", {"servers": {"p": [
        "sh", "-c", "echo starting; echo \"error: no such option, base $WEB_BASE\" >&2; exit 2"]}})
    monkeypatch.setattr(web, "servers", {})
    with pytest.raises(ValueError, match=r"p's server exited with 2: error: no such option, base /plugins/p"):
        web.plugin_server("p")
    run_dir = os.path.dirname(web.servers["p"][1])
    with pytest.raises(ValueError):  # a second try starts afresh, and clears the failed one away
        web.plugin_server("p")
    assert not os.path.exists(run_dir)
    with pytest.raises(ValueError, match="no project here has a server of the plugin q"):
        web.plugin_server("q")


def test_a_session_outlives_its_tabs_until_stopped_or_deleted(tmp_path, monkeypatch):
    docker = tmp_path / "docker"
    docker.write_text(f'#!/bin/sh\necho "$*" >>"{tmp_path}/docker-calls"\n')
    docker.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    monkeypatch.setattr(web, "command", lambda *_: ["sleep", "30"])
    monkeypatch.setattr(web, "KEEPALIVE", 0.2)
    server = web.serve(0, configured(tmp_path, monkeypatch))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    post = lambda path, method="POST": urllib.request.urlopen(urllib.request.Request(  # noqa: E731
        base + path, b"", headers={"Origin": base}, method=method), timeout=5)
    stopped = web.start(str(tmp_path), "resume", "0a1b2c")
    deleted = web.start(str(tmp_path), "resume", "3d4e5f")
    try:
        urllib.request.urlopen(f"{base}/api/sessions/{stopped.id}/events", timeout=5).close()
        for _ in range(10):  # a few keepalives: the closed tab is long noticed
            time.sleep(0.1)
        assert (stopped.exit, stopped.listeners) == (None, [])  # the tab is let go, the session runs on

        post(f"/api/sessions/{stopped.id}/stop")
        post(f"/api/sessions/{deleted.id}", "DELETE")  # still running: stopped first
        calls = tmp_path / "docker-calls"
        for _ in range(50):
            if None not in (stopped.exit, deleted.exit) and len(calls.read_text().splitlines()) == 2 \
                    and not deleted.dir.exists():
                break
            time.sleep(0.1)
        assert sorted(calls.read_text().splitlines()) == ["rm -f sandbox-0a1b2c", "rm -f sandbox-3d4e5f"]
        assert list(web.sessions) == [stopped.id]  # the stopped one stays listed, to read and resume
        assert not deleted.dir.exists()  # what it held let go of once it had ended
    finally:
        stopped.stop()
        deleted.stop()
        server.shutdown()
        web.sessions.clear()


@pytest.mark.parametrize("event, said", [
    ({"hook_event_name": "UserPromptSubmit"}, b"working"),
    ({"hook_event_name": "PreToolUse", "tool_name": "Bash"}, b"working"),
    ({"hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion"}, b"question"),
    ({"hook_event_name": "PostToolUse", "tool_name": "AskUserQuestion"}, b"working"),
    ({"hook_event_name": "Notification", "notification_type": "permission_prompt"}, b"question"),
    ({"hook_event_name": "Notification", "notification_type": "idle_prompt"}, b"idle"),
    ({"hook_event_name": "Stop"}, b"idle"),
    ({"hook_event_name": "SessionStart"}, b""),
])
def test_the_agent_status_hook_writes_its_state_to_the_agents_terminal(event, said):
    """The hook finds the terminal through its parent (here, the shell holding the pty) and writes
    its marker (an iTerm2-style user var, for the terminal run.sh runs in); it never prints anything
    or fails the agent's tool call."""
    import pty
    hook = REPO / "plugins/agent-status/bin/agent-status.py"
    pid, fd = pty.fork()
    if pid == 0:  # a shell on the pty, running the hook with pipes for stdio, as Claude Code does
        os.execv("/bin/sh", ["sh", "-c", f"echo '{json.dumps(event)}' | {hook} >/dev/null 2>&1 </dev/stdin;"
                                         " echo rc=$?"])
    got = b""
    while True:
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        got += chunk
    os.waitpid(pid, 0)
    found = re.findall(rb"\x1b\]1337;SetUserVar=agent_status=([A-Za-z0-9+/=]*)(?:\x07|\x1b\\)", got)
    assert [base64.b64decode(f) for f in found] == ([said] if said else [])
    assert got.endswith(b"rc=0\r\n")


def test_on_status_tells_each_change_of_the_status_the_page_shows(chat, monkeypatch):
    """on_status(): each change of a session's status, as its dot shows it (idle with background
    tasks running is working), runs the project's web_on_status commands with the change on stdin;
    a session first seen is not a change."""
    told = chat.tmp / "told"
    record = [sys.executable, "-c", f"import sys; open({str(told)!r}, 'a').write(sys.stdin.read() + '\\n')"]
    monkeypatch.setattr(web, "page_origin", "http://box:8787")
    monkeypatch.setitem(web.described, str(chat.tmp), {"on_status": {"agent-status": record}})
    last = {}

    def changes(n):
        for _ in range(100):  # each command runs on a thread of its own
            said = told.read_text().splitlines() if told.exists() else []
            if len(said) >= n:
                time.sleep(0.1)
                return [(e["before"], e["status"]) for e in map(json.loads, told.read_text().splitlines())]
            time.sleep(0.05)
        raise AssertionError(f"told {said}")

    s = chat()
    web.on_status(last)  # first seen: starting
    chat.until(s, lambda s: s.ready)
    web.on_status(last)
    changes(1)  # told before the next change is, or the two threads may write in either order
    s.prompt("run it in the background")
    chat.until(s, lambda s: s.status() == "working")
    web.on_status(last)
    chat.until(s, lambda s: s.status() == "idle" and len(s.tasks) == 2)
    web.on_status(last)  # its turn is over, but two tasks run on: still working
    assert changes(2) == [("starting", "idle"), ("idle", "working")]
    for task in ("bg1a", "bg1b"):
        s.tell({"type": "task", "id": task})
    chat.until(s, lambda s: not s.tasks)
    web.on_status(last)
    web.on_status(last)  # once per change
    assert changes(3)[2:] == [("working", "idle")]
    event = json.loads(told.read_text().splitlines()[-1])
    assert event == {"project": str(chat.tmp), "run_id": s.run_id, "session": s.id, "url": f"http://box:8787/chat#{s.id}",
                     "status": "idle", "before": "working"}


@pytest.mark.parametrize("kind", ["generic", "google-chat"])
def test_agent_status_posts_idle_and_question_to_its_webhook_but_not_the_boot(tmp_path, kind):
    """plugins/agent-status/host/notify.py, the web_on_status command: idle and question are
    posted with a link to the session's page, the boot that ends in idle and working are not;
    to Google Chat as its text alone."""
    import http.server
    got = []

    class Hook(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            got.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *_):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Hook)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    hook = [str(REPO / "plugins/agent-status/host/notify.py"), f"http://127.0.0.1:{server.server_port}/", kind]
    page = "http://box:8787/chat#ab12cd34"
    try:
        for before, status in [("starting", "idle"), ("idle", "working"), ("working", "idle"), ("idle", "question")]:
            event = {"project": "/home/me/projects/demo", "run_id": "0a1b2c", "session": "ab12cd34", "url": page,
                     "status": status, "before": before}
            done = subprocess.run(hook, input=json.dumps(event), text=True, capture_output=True)
            assert (done.returncode, done.stderr) == (0, "")
    finally:
        server.shutdown()
    texts = [f"demo (0a1b2c): idle, waiting for its next task\n{page}", f"demo (0a1b2c): needs you\n{page}"]
    if kind == "google-chat":
        assert got == [{"text": t} for t in texts]
    else:
        assert got == [{"text": t, "content": t, "project": "demo", "run_id": "0a1b2c", "status": s, "url": page}
                       for t, s in zip(texts, ["idle", "question"])]


def test_deleting_tidies_up_only_what_a_plugin_offered_for_that_run(tmp_path, monkeypatch):
    """offers(): the run's items with an on_delete, none while another session of the run is
    listed; tidy(): runs `run.sh --web-action` for those of them the page's user said yes to."""
    from types import SimpleNamespace as NS
    log = tmp_path / "actions"
    run_sh = tmp_path / "run.sh"
    run_sh.write_text(f'#!/bin/sh\necho "$*" >>"{log}"\n[ "$6" != 9 ] || {{ echo "❌ gh pr close: gone" >&2; exit 1; }}\n')
    run_sh.chmod(0o755)
    monkeypatch.setattr(web, "RUN_SH", run_sh)
    close = lambda n: {"plugin": "github-auth", "action": "close-pr", "arg": n, "ask": f"Close #{n}?"}  # noqa: E731
    monkeypatch.setitem(web.described, str(tmp_path), {"lists": [], "run_items": [
        {"ref": "#3", "url": "u3", "run_id": "0a1b2c", "on_delete": close("3")},
        {"ref": "#9", "url": "u9", "run_id": "0a1b2c", "on_delete": close("9")},
        {"ref": "#2", "url": "u2", "run_id": "0a1b2c"},                          # merged: nothing to do
        {"ref": "#4", "url": "u4", "run_id": "ffffff", "on_delete": close("4")},  # another run's
    ]})
    s = NS(id="a", project=str(tmp_path), run_id="0a1b2c")
    other = NS(id="b", project=str(tmp_path), run_id="0a1b2c")
    monkeypatch.setattr(web, "sessions", {"a": s, "b": other})
    assert web.offers(s) == []  # the run goes on in its other session
    monkeypatch.setattr(web, "sessions", {"a": s})
    offered = web.offers(s)
    assert [i["ref"] for i in offered] == ["#3", "#9"]
    assert web.tidy(s, ["u3", "u4", "u2"], offered) == []  # only #3: u4 is not this run's, u2 offers nothing
    assert log.read_text() == f"--project {tmp_path} --web-action github-auth close-pr 3\n"
    assert web.tidy(s, ["u9"], offered) == ["#9: ❌ gh pr close: gone"]


def test_a_demo_is_up_once_its_server_answers_not_once_its_port_is_published(monkeypatch):
    """Docker takes a published port's connections before the server in the container listens, and
    closes them unanswered: the demo's lamp is lit by an HTTP answer, of any status."""
    def until(item, up):
        for _ in range(100):
            if web.answering(item)["up"] == up:
                return True
            time.sleep(0.05)
    monkeypatch.setattr(web, "UP_EVERY", 0)
    published = socket.create_server(("127.0.0.1", 0))  # takes the connection, says nothing
    item = {"run_id": "0a1b2c", "port": 5173, "upstream": ["127.0.0.1", published.getsockname()[1]]}

    def mute():
        while True:
            try:
                published.accept()[0].close()
            except OSError:
                return
    threading.Thread(target=mute, daemon=True).start()
    assert web.answering(item) == {**item, "up": False}  # asked in the background: not up until it said so
    time.sleep(0.3)
    assert web.answering(item)["up"] is False
    published.close()
    with socket.create_server(("127.0.0.1", 0)) as app:
        item = {**item, "upstream": ["127.0.0.1", app.getsockname()[1]]}

        def answer():
            c = app.accept()[0]
            c.recv(1024)
            c.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
            c.close()
        threading.Thread(target=answer, daemon=True).start()
        assert until(item, True)
    assert web.answering({"ref": "#3"}) == {"ref": "#3"}  # no upstream: nothing to ask


def test_a_running_sessions_live_items_are_read_afresh_on_every_poll(tmp_path, monkeypatch):
    """web_live_items: a file a plugin keeps current (the central port proxy's published ports),
    re-read for each running session; an ended session shows none."""
    from types import SimpleNamespace as NS
    live = tmp_path / "items.json"
    monkeypatch.setitem(web.described, str(tmp_path), {"lists": [], "live": [str(live), str(tmp_path / "none")]})
    assert web.live_items(str(tmp_path), "0a1b2c") == []  # nothing published yet
    port = {"run_id": "0a1b2c", "ref": ":3000", "url": "http://{host}:3000/", "title": "Port 3000"}
    live.write_text(json.dumps([port, {"run_id": "ffffff", "ref": ":3000", "url": "x"}, "junk"]))
    assert web.live_items(str(tmp_path), "0a1b2c") == [port]
    assert web.live_items(str(tmp_path), None) == []
    s = NS(project=str(tmp_path), run_id="0a1b2c", exit=None, kind="resume", id="a", started=0, shown=lambda: None,
           title="", activity="", said="", info={}, cost=None, context=None, waiting=[], todos=[])
    assert web.Session.json(s)["items"] == [port]
    s.exit = 0
    assert web.Session.json(s)["items"] == []


# ---- chats: an agent behind its chat bridge, `run.sh --chat` on pipes ----------------------------

STUB = REPO / "tests/stubs/chat_run.py"  # a sandbox that boots, then an agent speaking chat events


@pytest.fixture
def chat(tmp_path, monkeypatch):
    """Starts chat sessions on the stub in place of run.sh; `chat.until(s, test)` waits for it."""
    stub = tmp_path / "run.sh"
    shutil.copy(STUB, stub)
    stub.chmod(0o755)
    docker = tmp_path / "bin/docker"
    docker.parent.mkdir()
    docker.write_text("#!/bin/sh\n")
    docker.chmod(0o755)
    monkeypatch.setattr(web, "RUN_SH", stub)
    monkeypatch.setenv("PATH", f"{tmp_path}/bin:/usr/bin:/bin")
    monkeypatch.setenv("STUB_BOOT", "0.05")
    started = []

    def start(kind="run", run_id=None, task=None):
        s = web.start(str(tmp_path), kind, run_id, task)
        started.append(s)
        return s

    def until(s, test, within=10):
        for _ in range(within * 50):
            with web.lock:
                if test(s):
                    return
            time.sleep(0.02)
        raise AssertionError(f"still {s.status()}: {s.events[-3:]}")
    start.until, start.tmp = until, tmp_path
    yield start
    started = [web.sessions.get(s.id, s) for s in started]  # the one a restart took it back as
    for s in started:
        s.stop()
    for s in started:
        until(s, lambda s: s.exit is not None)
    web.sessions.clear()


def test_prompts_typed_while_the_sandbox_starts_wait_and_reach_the_agent_in_order(chat, monkeypatch):
    monkeypatch.setenv("STUB_BOOT", "0.2")
    s = chat(task="first, please")  # a task is simply the first message
    assert (s.status(), s.json()["title"]) == ("starting", "first, please")
    s.prompt("then ask me")
    assert [(e["text"], e.get("queued")) for e in s.events if e["type"] == "user"] == [
        ("first, please", True), ("then ask me", True)]
    assert s.json()["waiting"] == 2 and not (chat.tmp / "commands").exists()  # nothing sent yet
    commands = chat.tmp / "commands"  # what the stand-in agent was sent, as it reads it
    chat.until(s, lambda s: s.ready and commands.exists() and len(commands.read_text().splitlines()) == 2)
    sent = [json.loads(line) for line in commands.read_text().splitlines()]
    assert sent == [{"type": "prompt", "text": "first, please"}, {"type": "prompt", "text": "then ask me"}]
    assert not any(e.get("queued") for e in s.events) and s.json()["waiting"] == 0
    chat.until(s, lambda s: s.status() == "question")
    boot = next(e for e in s.events if e["type"] == "boot")
    assert "🤖 Agent: claude" in boot["text"] and "Cloning into /workspace" in boot["text"]  # one entry, every line
    assert s.info["model"] == "fable" and [c["name"] for c in s.info["commands"]][0] == "compact"


def test_model_and_effort_picked_while_the_sandbox_starts_reach_the_agent_before_the_first_prompt(chat, monkeypatch):
    monkeypatch.setenv("STUB_BOOT", "0.2")
    s = chat(task="go")
    assert "models" not in s.info  # this project's agent has not said yet what it offers
    s.tell({"type": "model", "id": "haiku"})
    s.tell({"type": "model", "id": "opus"})  # the last pick wins
    s.tell({"type": "effort", "level": "high"})
    assert (s.info["model"], s.info["effort"]) == ("opus", "high")  # a page opened now shows the picks
    commands = chat.tmp / "commands"
    chat.until(s, lambda s: s.ready and commands.exists() and len(commands.read_text().splitlines()) == 3)
    assert [json.loads(line) for line in commands.read_text().splitlines()] == [
        {"type": "model", "id": "opus"}, {"type": "effort", "level": "high"}, {"type": "prompt", "text": "go"}]
    chat.until(s, lambda s: s.info["model"] == "opus" and not s.pending)
    later = chat()  # the next chat of the project offers them from the start
    assert later.status() == "starting" and [m["id"] for m in later.info["models"]][0] == "fable"
    assert later.info["efforts"] == ["low", "medium", "high"] and later.info["commands"]
    assert web.agent_offers()[str(chat.tmp)]["efforts"] == ["low", "medium", "high"]  # in a file: a restarted server has it


def test_a_chat_keeps_the_conversation_for_a_page_opened_later(chat):
    s = chat()
    chat.until(s, lambda s: s.ready)
    assert s.status() == "idle"
    s.prompt("change it")
    chat.until(s, lambda s: s.status() == "idle" and any(e["type"] == "turn" for e in s.events))
    snap = json.loads(json.dumps(s.snapshot()))
    kinds = [e["type"] for e in snap["events"]]
    assert "delta" not in kinds and kinds.count("user") == 1  # streamed text is folded into its block
    answer = next(e for e in snap["events"] if e["type"] == "text" and e["id"] == "a1")
    assert answer["text"].startswith("Done with “change it”.")
    edit = next(e for e in snap["events"] if e["type"] == "tool" and e["name"] == "Edit")
    assert (edit["done"], edit["error"], edit["output"]) == (True, False, "The file has been updated.")
    assert next(e for e in snap["events"] if e.get("parent"))["name"] == "Grep"  # a subagent's call, under its parent
    assert snap["todos"][-1] == {"text": "Run the tests", "status": "done"}
    told = s.json()
    assert (told["cost"], told["context"], told["status"]) == (0.1, {"used": 30000, "max": 1000000}, "idle")
    assert told["said"].endswith("for more.") and told["activity"] == ""


PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="  # one pixel


def test_a_chat_lists_what_runs_in_the_background_and_stops_one_on_request(chat):
    s = chat()
    chat.until(s, lambda s: s.ready)
    s.prompt("run it in the background")
    chat.until(s, lambda s: len(s.tasks) == 2 and s.status() == "idle")  # the turn is over, they run on
    assert s.json()["status"] == "working"  # and the dashboard shows it working while they do
    assert s.snapshot()["tasks"] == [{"id": "bg1a", "kind": "shell", "text": "npm run dev"},
                                     {"id": "bg1b", "kind": "agent", "text": "Check the callers", "note": "Reading src/app.py"}]
    assert not any(e["type"] == "tasks" for e in s.events)  # the latest set, not a log of them
    s.tell({"type": "task", "id": "bg1a"})
    chat.until(s, lambda s: [t["id"] for t in s.tasks] == ["bg1b"])
    s.stop()
    chat.until(s, lambda s: s.exit is not None)
    assert s.tasks == []  # nothing runs once it has ended


def test_a_call_the_agent_waits_on_can_be_sent_to_the_background_or_stopped(chat):
    s = chat()
    chat.until(s, lambda s: s.ready)
    s.prompt("a long one")
    chat.until(s, lambda s: any(e["type"] == "foreground" for e in s.events))
    assert [e for e in s.snapshot()["events"] if e["type"] == "foreground"] == [{"type": "foreground", "id": "b1", "task": "fg1"}]
    s.tell({"type": "background", "id": "b1"})  # the call returns, its task runs on in the background
    chat.until(s, lambda s: [t["id"] for t in s.tasks] == ["fg1"] and s.status() == "idle")
    assert next(e for e in s.events if e["type"] == "tool" and e["id"] == "b1")["done"] is True
    s.prompt("another long one")
    chat.until(s, lambda s: any(e["type"] == "foreground" and e["id"] == "b2" for e in s.events))
    s.tell({"type": "task", "id": "fg2"})  # stopped: the call ends as failed, the turn goes on
    chat.until(s, lambda s: s.status() == "idle" and next(e for e in s.events if e.get("id") == "b2")["done"])
    assert next(e for e in s.events if e["type"] == "tool" and e["id"] == "b2")["error"] is True


def test_a_prompt_sent_again_under_the_same_nonce_is_taken_once(chat):
    s = chat()
    chat.until(s, lambda s: s.ready)
    s.prompt("once", nonce="n-1")
    s.prompt("once", nonce="n-1")  # the page could not tell it arrived, and tried again
    users = [e for e in s.events if e["type"] == "user"]
    assert [(e["text"], e["nonce"]) for e in users] == [("once", "n-1")]
    with pytest.raises(ValueError):
        s.prompt("x", nonce=["not", "a", "string"])


def test_a_prompt_takes_the_images_pasted_into_it(chat, monkeypatch):
    monkeypatch.setenv("STUB_BOOT", "0.2")
    picture = {"type": "image/png", "data": PNG}
    s = web.start(str(chat.tmp), "run", None, images=[picture])  # a first message of only a picture
    try:
        assert s.json()["title"] == "Image" and s.events[0] == {"type": "user", "id": "u1", "text": "", "images": [picture], "queued": True}
        chat.until(s, lambda s: s.ready)
        s.prompt("and this one", [{**picture, "name": "left out"}])
        commands = chat.tmp / "commands"
        chat.until(s, lambda s: commands.exists() and len(commands.read_text().splitlines()) == 2)
        assert [json.loads(line) for line in commands.read_text().splitlines()] == [
            {"type": "prompt", "text": "", "images": [picture]}, {"type": "prompt", "text": "and this one", "images": [picture]}]
        assert any(e.get("text") == "and this one" and e["images"] == [picture] for e in s.snapshot()["events"])  # kept, for a page opened later
        for bad in ([{"type": "image/svg+xml", "data": PNG}], [{"type": "image/png", "data": "<script>"}], [picture] * 9, "x",
                    [{"type": "image/png", "data": "A" * (7 << 20)}]):
            with pytest.raises(ValueError):
                s.prompt("look", bad)
    finally:
        s.stop()
        chat.until(s, lambda s: s.exit is not None)


def test_a_prompt_takes_files_and_its_events_keep_only_their_names(chat):
    s = chat()
    try:
        chat.until(s, lambda s: s.ready)
        notes = {"name": "notes.txt", "data": "aGk="}
        s.prompt("", None, [notes])
        commands = chat.tmp / "commands"
        chat.until(s, lambda s: commands.exists())
        assert json.loads(commands.read_text().splitlines()[-1]) == {"type": "prompt", "text": "", "files": [notes]}
        [said] = [e for e in s.events if e["type"] == "user"]
        assert s.json()["title"] == "File" and said["files"] == ["notes.txt"] and "aGk=" not in str(said)
        for bad in ([{"name": "../x", "data": "aGk="}], [{"name": "x", "data": "<b>"}], [{"name": "", "data": ""}], [notes] * 9,
                    [{"name": "big", "data": "A" * (14 << 20)}], "x"):
            with pytest.raises(ValueError):
                s.prompt("look", None, bad)
    finally:
        s.stop()
        chat.until(s, lambda s: s.exit is not None)


def test_a_chat_streams_its_events_and_takes_answers_and_interrupts(chat, tmp_path, monkeypatch):
    server = web.serve(0, configured(tmp_path, monkeypatch))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def post(path, body=None, origin=base, method="POST"):
        req = urllib.request.Request(base + path, json.dumps(body or {}).encode(), method=method,
                                     headers={"Origin": origin, "Content-Type": "application/json"})
        try:
            return urllib.request.urlopen(req, timeout=5).status
        except urllib.error.HTTPError as e:
            return e.code
    try:
        s = json.load(urllib.request.urlopen(urllib.request.Request(base + "/api/sessions", json.dumps(
            {"project": "proj", "kind": "run"}).encode(), {"Content-Type": "application/json"})))
        assert s["status"] == "starting" and "ui" not in s  # every session is a chat
        assert json.load(urllib.request.urlopen(f"{base}/api/sessions/{s['id']}"))["id"] == s["id"]
        assert [x["id"] for x in json.load(urllib.request.urlopen(f"{base}/api/sessions"))["sessions"]] == [s["id"]]
        live = web.sessions[s["id"]]
        events = urllib.request.urlopen(f"{base}/api/sessions/{s['id']}/events", timeout=10)

        def read(until):
            for line in events:
                if line.startswith(b"data: "):
                    event = json.loads(line[6:])
                    if until(event):
                        return event
        assert read(lambda e: True)["type"] == "snapshot"  # the page starts from the whole session
        assert read(lambda e: e["type"] == "ready")["efforts"] == ["low", "medium", "high"]
        assert post(f"/api/sessions/{s['id']}/messages", {"text": "ask me"}) == 200
        asked = read(lambda e: e["type"] == "ask")
        assert read(lambda e: e["type"] == "status")["state"] == "question"
        assert post(f"/api/sessions/{s['id']}/questions/{asked['id']}/answer", {"answers": {"Which database?": "SQLite"}}) == 200
        assert read(lambda e: e["type"] == "text" and e["id"] == "a1")["text"] == "Going with **SQLite**."
        with web.lock:  # the answer is kept with its question, for a page opened later
            assert [(e["answers"], e.get("done")) for e in live.events if e["type"] == "ask"] == [
                ({"Which database?": "SQLite"}, True)]
        read(lambda e: e["type"] == "status" and e["state"] == "idle")

        assert post(f"/api/sessions/{s['id']}/messages", {"text": "a long one"}) == 200
        read(lambda e: e["type"] == "tool" and e["name"] == "Bash")
        assert live.json()["activity"] == "Bash: Wait a long time"
        assert post(f"/api/sessions/{s['id']}/interrupt") == 200
        assert read(lambda e: e["type"] == "result" and e["id"] == "b2")["error"] is True
        assert post(f"/api/sessions/{s['id']}/model", {"id": "opus"}, method="PUT") == 200
        assert read(lambda e: e["type"] == "model")["id"] == "opus"

        assert post(f"/api/sessions/{s['id']}/messages", {"text": "  "}) == 400        # not a message
        assert post(f"/api/sessions/{s['id']}/model", {"id": "opus"}) == 405           # PUT, not POST
        assert post("/api/sessions/nosuch/messages", {"text": "x"}) == 404             # no such session
        for gone in ("input", "resize?cols=80&rows=24", "prompt"):                     # no terminals; messages, not prompts
            assert post(f"/api/sessions/{s['id']}/{gone}") == 404
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(f"{base}/api/sessions/{s['id']}/stream", timeout=5)  # nor a terminal's stream
        assert e.value.code == 404
        assert post(f"/api/sessions/{s['id']}/messages", {"text": "x"}, "http://evil.example") == 403  # nor another site's page
    finally:
        live.stop()
        chat.until(live, lambda s: s.exit is not None)
        server.shutdown()


def test_a_chat_that_ends_says_so_and_takes_no_more_prompts(chat, monkeypatch):
    s = chat(task="now exit")
    chat.until(s, lambda s: s.exit is not None)
    assert (s.exit, s.status(), s.events[-1]) == (3, None, {"type": "exit", "code": 3})
    with pytest.raises(ValueError, match="has ended"):
        s.prompt("anyone there?")
    monkeypatch.setenv("STUB_BOOT_FAILS", "1")
    failed = chat(task="never delivered")  # the boot fails: what it printed is all there is to show
    chat.until(failed, lambda s: s.exit is not None)
    assert not failed.ready and failed.exit == 1
    assert "GH_PRIVATE_KEY_FILE not found" in next(e for e in failed.events if e["type"] == "boot")["text"]
    assert [e.get("queued") for e in failed.events if e["type"] == "user"] == [True]


def test_a_resumed_chat_replays_what_was_said_before(chat):
    s = chat("resume", "0a1b2c")
    chat.until(s, lambda s: s.ready)
    assert [(e["type"], e["text"]) for e in s.events if e["type"] in ("user", "text")] == [
        ("user", "What was said before the resume"), ("text", "An earlier answer.")]
    assert chat("resume", "0a1b2c") is s  # one live session per run
    s.title = "Fix the board"
    s.stop()
    chat.until(s, lambda s: s.exit is not None)
    again = chat("resume", "0a1b2c")  # it takes the ended one's place, and its name: a run stays one session
    assert list(web.sessions) == [again.id] and again.title == "Fix the board"


def test_a_prompt_written_while_a_resumed_chat_boots_comes_after_the_replayed_conversation(chat):
    hold = chat.tmp / "hold"
    hold.touch()
    s = chat("resume", "0a1b2c")
    s.prompt("go on please")
    hold.unlink()
    chat.until(s, lambda s: s.ready and any(e["type"] == "turn" for e in s.events))
    assert [e["text"] for e in s.events if e["type"] == "user"] == ["What was said before the resume", "go on please"]


def sent_prompts(chat):
    """The prompts the stand-in agents were sent, in order."""
    commands = chat.tmp / "commands"
    lines = commands.read_text().splitlines() if commands.exists() else []
    return [c["text"] for c in map(json.loads, lines) if c["type"] == "prompt"]


@pytest.mark.parametrize("task, said", [("long", "while you were working on your turn"),
                                        ("ask me", "waiting for the user's answer to your question (ask it again)")])
def test_a_chat_stopped_mid_turn_or_mid_question_carries_on_when_resumed(chat, task, said):
    s = chat(task=task)
    chat.until(s, lambda s: s.status() == ("working" if task == "long" else "question"))
    s.stop()  # even the user's Stop: it carries on when resumed
    chat.until(s, lambda s: s.exit is not None)
    again = chat("resume", s.run_id)
    chat.until(again, lambda s: s.ready and len(sent_prompts(chat)) == 2)
    assert sent_prompts(chat)[0] == task
    carry = sent_prompts(chat)[1]
    assert carry.startswith("<session-resumed>") and said in carry and "Carry on where you left off." in carry
    assert again.resuming is None and any(e["type"] == "notice" and "carries on" in e["text"] for e in again.events)


def test_a_chat_stopped_while_idle_resumes_idle(chat):
    s = chat(task="change it")
    chat.until(s, lambda s: s.status() == "idle" and any(e["type"] == "turn" for e in s.events))
    s.stop()
    chat.until(s, lambda s: s.exit is not None)
    assert s.stopped_in == "idle"
    again = chat("resume", s.run_id)
    chat.until(again, lambda s: s.ready)
    time.sleep(0.2)
    assert sent_prompts(chat) == ["change it"] and again.status() == "idle"


def test_a_chat_stopped_with_background_tasks_tells_the_resumed_agent_they_were_stopped(chat):
    s = chat(task="background")
    chat.until(s, lambda s: len(s.tasks) == 2)
    s.stop()
    chat.until(s, lambda s: s.exit is not None)
    assert (s.stopped_in, s.killed) == ("working", ["npm run dev", "Check the callers"])
    again = chat("resume", s.run_id)
    chat.until(again, lambda s: len(sent_prompts(chat)) == 2)
    assert "was stopped with it: npm run dev; Check the callers." in sent_prompts(chat)[1]


def test_prompts_and_picks_that_never_reached_a_stopped_chat_reach_its_resumed_one(chat):
    hold = chat.tmp / "hold"
    hold.touch()
    s = chat(task="first")
    s.prompt("second")
    s.tell({"type": "model", "id": "opus"})
    s.stop()
    chat.until(s, lambda s: s.exit is not None)
    hold.unlink()
    again = chat("resume", s.run_id)
    assert [e["text"] for e in again.events if e["type"] == "user"] == ["first", "second"] and again.json()["waiting"] == 2
    commands = chat.tmp / "commands"
    chat.until(again, lambda s: len(sent_prompts(chat)) == 2)
    assert [json.loads(line) for line in commands.read_text().splitlines()] == [
        {"type": "model", "id": "opus"}, {"type": "prompt", "text": "first"}, {"type": "prompt", "text": "second"}]


def test_a_chat_killed_with_the_machine_is_resumed_by_the_next_server_and_carries_on(chat):
    s = chat(task="long")
    chat.until(s, lambda s: s.status() == "working")
    with web.lock:  # a reboot: the server, the holder and the sandbox go at once, without a word
        s.save()
        s._data = s._end = s.save = s.close = lambda *_: None
        s.sock.shutdown(socket.SHUT_RDWR)
        holder = int(Path(f"/proc/{s.pid}/stat").read_text().rsplit(")", 1)[1].split()[1])  # its child's parent
        os.kill(holder, signal.SIGKILL)  # first, so it cannot say how its child ended
        os.killpg(s.pid, signal.SIGKILL)  # the sandbox: a group of its own
        web.sessions.clear()
    for _ in range(100):
        try:
            os.kill(s.pid, 0)
            time.sleep(0.02)
        except ProcessLookupError:
            break
    assert not (s.dir / "exit").exists()
    s.exit = -1  # what the old server knew of it is gone with it
    web.restore()
    for _ in range(250):
        with web.lock:
            back = next((b for b in web.sessions.values() if b.run_id == s.run_id and b.exit is None), None)
        if back:
            break
        time.sleep(0.02)
    assert back is not None and back.kind == "resume" and len(web.sessions) == 1  # it took the ended one's place
    chat.until(back, lambda s: len(sent_prompts(chat)) == 2)
    assert "while you were working on your turn" in sent_prompts(chat)[1]
    back.stop()
    chat.until(back, lambda s: s.exit is not None)


def test_a_chat_that_ended_by_itself_while_no_server_listened_stays_ended(chat):
    s = chat(task="now exit")
    with web.lock:
        s.save()
        s._data = s._end = s.save = s.close = lambda *_: None
        s.sock.shutdown(socket.SHUT_RDWR)
        web.sessions.clear()
    for _ in range(250):
        if (s.dir / "exit").exists():
            break
        time.sleep(0.02)
    web.restore()
    time.sleep(0.3)
    assert [(b.id, b.exit) for b in web.sessions.values()] == [(s.id, 3)]


def test_a_session_under_a_system_unit_goes_into_a_system_scope(tmp_path, monkeypatch):
    """A system unit has no user manager to ask: its sessions must not stay in its cgroup, a restart stops that."""
    spawned = []
    monkeypatch.setattr(web, "scoped", [])
    monkeypatch.setenv("INVOCATION_ID", "x")
    monkeypatch.setattr(web.shutil, "which", lambda _: "/usr/bin/systemd-run")
    monkeypatch.setattr(web.subprocess, "run", lambda cmd, **_: subprocess.CompletedProcess(cmd, int("--user" in cmd)))
    monkeypatch.setattr(web.subprocess, "Popen", lambda cmd, **_: spawned.append(cmd))
    web.hold(tmp_path, ["true"], tmp_path)
    assert spawned[0][:2] == ["systemd-run", "--scope"]


def test_a_side_chat_is_asked_beside_the_conversation_and_kept_apart_from_it(chat):
    s = chat()
    with pytest.raises(ValueError, match="not ready"):
        s.side(None, "too early")
    chat.until(s, lambda s: s.ready)
    heard = queue.Queue()
    s.listeners.append(heard)
    first = s.side(None, "why main?")
    assert first == "1" and s.side(None, "wait long") == "2"  # each a chat of its own
    chat.until(s, lambda s: s.sides["1"]["state"] == "idle")
    assert s.sides["2"]["state"] == "working" and s.status() == "idle" and [e["type"] for e in s.events] == ["boot"]  # the run's conversation knows nothing of it
    s.tell({"type": "interrupt", "side": "2"})
    chat.until(s, lambda s: s.sides["2"]["state"] == "idle")
    s.side("1", "and then?")
    chat.until(s, lambda s: s.sides["1"]["state"] == "idle")
    snap = json.loads(json.dumps(s.snapshot()))
    assert [(c["id"], c["title"], c["state"]) for c in snap["sides"]] == [("1", "why main?", "idle"), ("2", "wait long", "idle")]
    assert [(e["type"], e.get("text")) for e in snap["sides"][0]["events"]] == [  # streamed text folded, as in the conversation
        ("user", "why main?"), ("text", "About “why main?”: it changed `main()`. "), ("turn", None),
        ("user", "and then?"), ("text", "About “and then?”: it changed `main()`. "), ("turn", None)]
    told = []
    while not heard.empty():
        told.append(heard.get())
    told = [e for e in told if e != {"type": "status", "state": "idle"}]  # the agent's own, said as it got ready
    assert told[0] == {"type": "user", "side": "1", "text": "why main?"} and all(e.get("side") in ("1", "2") for e in told)
    back = restart()[s.id]  # kept through a restart of the server
    assert [c["title"] for c in back.snapshot()["sides"]] == ["why main?", "wait long"]
    assert back.side("2", None, close=True) == "2" and list(back.sides) == ["1"]
    assert back.side(None, "a third") == "3"  # an id is not used twice
    with pytest.raises(ValueError, match="no such side chat"):
        back.side("2", "gone")
    chat.until(back, lambda s: s.sides["3"]["state"] == "idle")  # the agent has read all it was sent
    commands = [json.loads(line) for line in (chat.tmp / "commands").read_text().splitlines()]
    assert {"type": "side", "id": "2", "close": True} in commands and {"type": "interrupt", "side": "2"} in commands


def test_a_resumed_chat_has_the_side_chats_its_agent_kept(chat):
    s = chat("resume", "0a1b2c")
    chat.until(s, lambda s: s.ready)
    assert [(c["id"], c["title"], [e["type"] for e in c["events"]]) for c in s.snapshot()["sides"]] == [
        ("1", "What was asked beside it", ["user", "text"])]
    assert s.side(None, "another") == "2"  # counted on from the ones it has


def test_sync_pulls_installs_and_restarts_only_under_systemd(monkeypatch):
    ran, spawned = [], []
    monkeypatch.setattr(web.subprocess, "run", lambda step, **_: ran.append(step) or subprocess.CompletedProcess(step, 0, "", ""))
    monkeypatch.setattr(web.subprocess, "Popen", lambda cmd, **_: spawned.append(cmd))
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    assert web.sync() == {"restarting": False} and not spawned
    assert ran[0][-4:] == ["pull", "--ff-only", "origin", "main"] and ran[1][0].endswith("install.sh")
    web.sync("claude-box.netbird.cloud")  # a service bound elsewhere stays bound there
    assert ran[-1][-2:] == ["--bind", "claude-box.netbird.cloud"] and "--bind" not in ran[1]
    monkeypatch.setenv("INVOCATION_ID", "x")
    assert web.sync() == {"restarting": True} and web.SERVICE in spawned[0][-1]
    monkeypatch.setattr(web.subprocess, "run", lambda step, **_: subprocess.CompletedProcess(step, 1, "", "not a fast-forward"))
    with pytest.raises(ValueError, match="not a fast-forward"):
        web.sync()


def restart():
    """What a restart of the server does to its sessions: this one stops listening (saving what it
    knew), and a new one takes them back from their holders."""
    with web.lock:
        for s in web.sessions.values():
            s.save()
            s._data = s._end = s.save = s.close = lambda *_: None  # the old server is gone: it does nothing more
            if hasattr(s, "sock"):
                s.sock.shutdown(socket.SHUT_RDWR)
        web.sessions.clear()
    web.restore()
    return {s.id: s for s in web.sessions.values()}


def test_a_chat_runs_on_through_a_restart_of_the_server(chat):
    s = chat(task="change it")
    chat.until(s, lambda s: s.ready)
    s.title = "Keep me"
    back = restart()[s.id]  # perhaps mid-turn: what it said meanwhile is caught up on, once
    chat.until(back, lambda s: s.status() == "idle" and any(e["type"] == "turn" for e in s.events))
    assert (back.title, back.ready, back.exit) == ("Keep me", True, None)
    assert [e["type"] for e in back.events].count("user") == 1 and [e["type"] for e in back.events].count("turn") == 1
    assert next(e for e in back.events if e.get("id") == "a1")["text"].startswith("Done with “change it”.")
    back.prompt("ask me")  # and it takes prompts as before
    chat.until(back, lambda s: s.status() == "question")
    back.stop()
    chat.until(back, lambda s: s.exit is not None)
    again = restart()[s.id]  # an ended one stays listed, to read and resume
    assert again.exit is not None and again.title == "Keep me" and again.events[-1]["type"] == "exit"


@pytest.mark.parametrize("was", [{"kind": "shell", "run_id": None}, {"ui": "terminal"}])
def test_a_shell_or_terminal_left_from_before_is_ended_not_taken_back(tmp_path, monkeypatch, was):
    """An older server's host shell (never again drivable from the page), or an agent's TUI in a
    terminal (there are none any more): ended, running or not, rather than taken back."""
    monkeypatch.setattr(web, "command", lambda *_: ["/bin/sh"])
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    (tmp_path / "docker").write_text("#!/bin/sh\n")
    (tmp_path / "docker").chmod(0o755)
    s = web.start("", "resume", "0a1b2c")
    meta = s.dir / "meta.json"
    meta.write_text(json.dumps({**json.loads(meta.read_text()), **was}))
    try:
        assert s.id not in restart()
        for _ in range(100):
            if not s.dir.exists():
                break
            time.sleep(0.05)
        assert not s.dir.exists()  # its holder ended it, and what it held is let go of
    finally:
        web.sessions.clear()


# ---- what plugins watch and start by themselves: web_poll, web_start -----------------------------

def test_the_poller_describes_each_project_as_often_as_its_plugins_asked(tmp_path, monkeypatch):
    """poller(): a project is described again once the shortest web_poll of its plugins has
    passed (never under 10 s), and one whose plugins asked for none every IDLE_POLL."""
    from types import SimpleNamespace as NS
    watched, quiet = tmp_path / "watched", tmp_path / "quiet"
    listing = tmp_path / "projects"
    listing.mkdir()
    for d in (watched, quiet):
        (listing / f"{d.name}.json").write_text("{}")
    now, seen = [1000.0], []

    def sleep(seconds):
        now[0] += seconds
        if now[0] > 1000 + web.IDLE_POLL + 6:
            raise StopIteration

    monkeypatch.setattr(web, "time", NS(time=lambda: now[0], sleep=sleep))
    monkeypatch.setattr(web, "describe", lambda project, keep=False: (
        seen.append((project, now[0] - 1000)), {"poll": 60} if project == "watched" else {"poll": None})[1])
    with pytest.raises(StopIteration):
        web.poller(listing)
    assert [at for p, at in seen if p == "watched"] == [0, 60, 120, 180, 240, 300]
    assert [at for p, at in seen if p == "quiet"] == [0, 300]


def test_a_plugin_starts_a_session_once_per_key_and_it_goes_when_its_agent_has_finished(chat, monkeypatch):
    """autostart(): what web_start asked for, as a run with its settings (`run.sh --set`) — not
    while a session of its `after_run` is listed, and never twice. The session is removed once
    its agent's turn is over; one whose turn failed stays to be read."""
    from types import SimpleNamespace as NS
    project = str(chat.tmp)
    want = lambda key, task: {"starts": [{"plugin": "pr-review", "key": key, "task": task,  # noqa: E731
                                           "env": {"GH_AUTH": "reviewer"}, "after_run": "0a1b2c"}]}
    monkeypatch.setitem(web.sessions, "x", NS(id="x", project=project, run_id="0a1b2c", kind="run", exit=0))
    web.autostart(project, want("#3@c3", "review it"))
    assert list(web.sessions) == ["x"]  # the run that opened it is still listed: its work is not over
    del web.sessions["x"]
    web.autostart(project, want("#3@c3", "review it"))
    [s] = web.sessions.values()
    assert s.once and s.title == "review it"
    assert web.command(s.project, s.kind, s.run_id, s.sets)[-5:] == ["--chat", "--set", "GH_AUTH=reviewer", "--set", "SANDBOX_STARTED_BY=pr-review"]
    chat.until(s, lambda s: s.id not in web.sessions and s.exit is not None)  # reviewed: gone, container and all
    web.autostart(project, want("#3@c3", "review it"))
    assert not web.sessions  # once per key, however often the project is described
    web.autostart(project, want("#3@c4", "fail"))  # a new commit is a new key
    [s] = web.sessions.values()
    chat.until(s, lambda s: s.state == "idle" and any(e["type"] == "turn" for e in s.events))
    time.sleep(0.2)
    assert s.id in web.sessions and s.exit is None  # its turn failed: it stays
    s.stop()
    chat.until(s, lambda s: s.exit is not None)


def test_serve_oauth_runs_the_server_behind_the_proxy_and_ends_with_it(tmp_path):
    # A stand-in oauth2-proxy: says how it was started, then answers until killed.
    stub = tmp_path / "bin/oauth2-proxy"
    stub.parent.mkdir()
    stub.write_text(f'#!/bin/sh\necho $$ > {tmp_path}/pid; echo "$@" > {tmp_path}/args\nexec sleep 60\n')
    stub.chmod(0o755)
    port = socket.socket()
    port.bind(("127.0.0.1", 0))
    upstream = port.getsockname()[1]
    port.close()
    env = {**os.environ, "PATH": f"{stub.parent}:{os.environ['PATH']}", "SANDBOX_WEB_UPSTREAM_PORT": str(upstream),
           "OAUTH2_PROXY_CLIENT_ID": "x", "OAUTH2_PROXY_CLIENT_SECRET": "s", "OAUTH2_PROXY_COOKIE_SECRET": "c" * 32}
    script = [str(REPO / "src/server/serve-oauth.sh"), "--host", "box.example.com"]
    missing = {k: v for k, v in env.items() if k != "OAUTH2_PROXY_COOKIE_SECRET"}
    assert subprocess.run(script, env=missing, capture_output=True).returncode == 2
    p = subprocess.Popen([*script, "--", "--extra"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):  # the server answers on loopback to the public name, as the proxy passes it
            try:
                urllib.request.urlopen(urllib.request.Request(
                    f"http://127.0.0.1:{upstream}/api/state", headers={"Host": "box.example.com"}), timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("the server did not come up")
        args = (tmp_path / "args").read_text()
        assert "--email-domain=levatioai.com" in args and f"--upstream=http://127.0.0.1:{upstream}/" in args
        # One sign-in for the demo servers too, subdomains of the host, under the name the server strips.
        assert "--cookie-domain=.box.example.com" in args and "--redirect-url=https://box.example.com/oauth2/callback" in args
        assert args.rstrip().endswith("--extra --cookie-name=_oauth2_proxy")
        os.kill(int((tmp_path / "pid").read_text()), 15)  # the proxy ending ends the server too
        p.wait(timeout=10)
        for _ in range(50):  # the server, told to go, goes (once what it was answering is answered)
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{upstream}/api/state", timeout=1)
                time.sleep(0.1)
            except OSError:
                break
        else:
            pytest.fail("the server outlived the proxy")
    finally:
        p.kill()


@pytest.fixture
def signing_agent(tmp_path, monkeypatch):
    """An agent whose `signIn` is `cli login`: like `claude auth login`, it prints its link (in an OSC 8
    hyperlink), then takes the code from stdin. `cli` is put in tmp_path; the caller puts it on a PATH."""
    agents = tmp_path / "agents"
    (agents / "a").mkdir(parents=True)
    (agents / "a/agent.json").write_text(json.dumps({"signIn": ["cli", "login"]}))
    (agents / "b").mkdir()
    (agents / "b/agent.json").write_text("{}")
    monkeypatch.setattr(web, "AGENTS", agents)
    cli = tmp_path / "cli"
    cli.write_text("#!/bin/sh\nprintf 'Opening\\nvisit: \\033]8;;https://claude.com/x?a=1\\007https://claude.com/x?a=1\\033]8;;\\007\\n'\n"
                   "printf 'Paste code here if prompted > '\nread c\n[ \"$c\" = good ] || { echo 'Bad code'; exit 1; }\n")
    cli.chmod(0o755)
    return cli


def test_an_agents_sign_in_gives_the_link_and_takes_back_its_code(signing_agent, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    assert web.sign_in("a") == "https://claude.com/x?a=1"
    with pytest.raises(ValueError, match="Bad code"):
        web.sign_in_code("a", "bad")
    with pytest.raises(ValueError, match="no sign-in under way"):
        web.sign_in_code("a", "good")
    web.sign_in("a")
    web.sign_in_code("a", " good ")
    for agent in ("b", "nope", "../a"):
        with pytest.raises(ValueError, match="has no sign-in"):
            web.sign_in(agent)



def api_server(tmp_path, monkeypatch):
    """This server in-process, on its own port; `call(method, path, body)` answers (status, JSON, headers)."""
    server = web.serve(0, configured(tmp_path, monkeypatch))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_):
            return None
    opener = urllib.request.build_opener(NoRedirect)

    def call(method, path, body=None):
        data = None if body is None else body if isinstance(body, bytes) else json.dumps(body).encode()
        try:
            got = opener.open(urllib.request.Request(base + path, data, {"Content-Type": "application/json"}, method=method), timeout=10)
        except urllib.error.HTTPError as e:
            got = e
        raw = got.read()
        return got.status, json.loads(raw) if raw else None, got.headers
    call.server = server
    return call


def test_each_of_a_chats_commands_is_a_resource_of_its_own(tmp_path, monkeypatch):
    """What the page asks of a chat, by method and path, reaches the session as the command it means."""
    told = []

    class Chat:
        id, exit = "c1", None

        def tell(self, command):
            told.append(("tell", command))

        def side(self, sid, text, close=False):
            told.append(("side", sid, text, close))
            return sid or "1"

        def prompt(self, text, images=None, files=None, nonce=None):
            if text == "fails":
                raise OSError("disk full")
            if text == "late":
                raise web.Conflict("this session has ended: resume it to go on")
            told.append(("prompt", text, images, files, nonce))

    monkeypatch.setitem(web.sessions, "c1", Chat())
    call = api_server(tmp_path, monkeypatch)
    try:
        for method, path, body, want, status, answer in [
            ("POST", "messages", {"text": "hi", "nonce": "n1"}, ("prompt", "hi", None, None, "n1"), 200, {}),
            ("POST", "interrupt", None, ("tell", {"type": "interrupt"}), 200, {}),
            ("POST", "questions/q7/answer", {"answers": {"A?": "b"}}, ("tell", {"type": "answer", "id": "q7", "answers": {"A?": "b"}}), 200, {}),
            ("POST", "questions/q7/answer", {"cancel": True}, ("tell", {"type": "answer", "id": "q7", "cancel": True}), 200, {}),
            ("PUT", "model", {"id": "opus"}, ("tell", {"type": "model", "id": "opus"}), 200, {}),
            ("PUT", "effort", {"level": "high"}, ("tell", {"type": "effort", "level": "high"}), 200, {}),
            ("DELETE", "tasks/t3", None, ("tell", {"type": "task", "id": "t3"}), 200, {}),
            ("POST", "calls/toolu_1/background", None, ("tell", {"type": "background", "id": "toolu_1"}), 200, {}),
            ("POST", "sides", {"text": "why?"}, ("side", None, "why?", False), 201, {"id": "1"}),
            ("POST", "sides/2/messages", {"text": "and?"}, ("side", "2", "and?", False), 200, {"id": "2"}),
            ("POST", "sides/2/interrupt", None, ("tell", {"type": "interrupt", "side": "2"}), 200, {}),
            ("DELETE", "sides/2", None, ("side", "2", None, True), 200, {}),
        ]:
            told.clear()
            got = call(method, f"/api/sessions/c1/{path}", body)
            assert (got[0], got[1], told) == (status, answer, [want]), (method, path)
        assert call("POST", "/api/sessions/c1/messages", {"text": "late"})[:2] == (409, {"error": "this session has ended: resume it to go on"})
        assert call("POST", "/api/sessions/c1/messages", {"text": "fails"})[:2] == (500, {"error": "disk full"})
        assert call("POST", "/api/sessions/c1/messages", b"[1]")[0] == 400  # a JSON object, or nothing
        assert call("POST", "/api/sessions/c1/messages", b"{")[0] == 400
        status, _, headers = call("POST", "/api/sessions/c1/model", {"id": "opus"})
        assert (status, headers["Allow"]) == (405, "PUT")
        assert call("GET", "/api/sessions/c2/events")[0] == 404  # no such session
        assert call("GET", "/api/nothing")[0] == 404
    finally:
        call.server.shutdown()
        web.sessions.clear()


def test_the_api_describes_itself_as_openapi(tmp_path, monkeypatch):
    call = api_server(tmp_path, monkeypatch)
    try:
        status, spec, _ = call("GET", "/api/openapi.json")
        assert status == 200 and spec["openapi"].startswith("3.")
        assert {"/api/sessions", "/api/sessions/{sid}/messages", "/api/projects/{name}/config", "/api/auth"} <= set(spec["paths"])
        assert "/" not in spec["paths"] and "/chat" not in spec["paths"]  # the pages are not API
        message = spec["components"]["schemas"]["Message"]
        assert message["required"] == ["text"] and "nonce" in message["properties"]
    finally:
        call.server.shutdown()


def test_an_item_a_plugin_lists_that_the_page_cannot_draw_is_left_out_with_a_note(tmp_path, monkeypatch):
    """What plugins describe comes from their shell scripts: an item without a url (or a live one
    without a title) is not the page's shape, and leaving it out keeps every answer it is in whole."""
    good = {"url": "https://x/pr/1", "title": "PR 1", "run_id": "0a1b2c"}
    live = tmp_path / "live.json"
    live.write_text(json.dumps([{**good, "url": "http://{host}:3000/"}, {"run_id": "0a1b2c", "url": "http://x"}]))
    said = {"lists": [{"title": "Pull requests", "items": [good, {"title": "no url"}]}, {"items": "junk"}],
            "notes": ["fine", 7], "run_items": [good, "junk"], "session_items": [{"url": 1, "title": "t"}],
            "agent": "claude", "plugins": ["git-workspace"], "live": [str(live)], "commands": {"x": {"y": ["rm", "-rf"]}}}
    stub = tmp_path / "run.sh"
    stub.write_text(f"#!/bin/sh\ncat <<'EOF'\n{json.dumps(said)}\nEOF\n")
    stub.chmod(0o755)
    monkeypatch.setattr(web, "RUN_SH", stub)
    call = api_server(tmp_path, monkeypatch)
    try:
        status, info, _ = call("GET", "/api/projects/proj")
        assert status == 200
        assert info["lists"] == [{"title": "Pull requests", "items": [good]}] and info["run_items"] == [good]
        assert info["session_items"] == [] and info["agent"] == "claude" and info["plugins"] == ["git-workspace"]
        assert info["notes"][0] == "fine" and len(info["notes"]) == 5 and all("left out" in n for n in info["notes"][1:])
        assert "1 list of the project left out" in " ".join(info["notes"])
        assert "commands" not in info and "live" not in info  # what the server runs is not the page's
        from types import SimpleNamespace as NS
        s = NS(project="proj", run_id="0a1b2c", exit=None, kind="run", id="a", started=0, shown=lambda: None,
               title="", activity="", said="", info={}, cost=None, context=None, waiting=[], todos=[])
        assert len(web.live_items("proj", "0a1b2c")) == 2  # the server's own, the relay's: as they are
        assert web.Session.json(s)["items"] == [{**good, "url": "http://{host}:3000/"}]  # the page's
    finally:
        call.server.shutdown()


def test_the_pages_types_are_generated_from_the_apis_description_and_current():
    """web/src/api/schema.ts is what api_types.py makes of models.py: a shape changed on one side and
    not the other fails here, in CI, rather than in the page."""
    import api_types
    assert (UI / "src/api/schema.ts").read_text() == api_types.generated(), \
        "web/src/api/schema.ts out of date: run `npm run api-types` in web"


def test_the_type_generator_writes_each_kind_of_schema():
    import api_types
    ts = api_types.ts
    assert ts({"anyOf": [{"type": "string"}, {"type": "null"}]}) == "string | null"
    assert ts({"type": "array", "items": {"anyOf": [{"type": "string"}, {"type": "number"}]}}) == "(string | number)[]"
    assert ts({"type": "array", "items": {"$ref": "#/components/schemas/Item"}}) == "Item[]"
    assert ts({"type": "object", "additionalProperties": {"type": "integer"}}) == "Record<string, number>"
    assert ts({"type": "object"}) == "Record<string, unknown>"
    assert ts({}) == "unknown" and ts({"const": "chat", "type": "string"}) == '"chat"'
    assert ts({"enum": ["a", "b"], "type": "string"}) == '"a" | "b"' and ts({"tsType": "Json", "type": "object"}) == "Json"
    out = api_types.interface("Thing", {"description": "A thing.", "required": ["id"], "additionalProperties": True,
                                        "properties": {"id": {"type": "string"}, "odd-name": {"type": "boolean", "description": "Odd."}}})
    assert out == ('/** A thing. */\nexport interface Thing {\n  id: string;\n  /** Odd. */\n  "odd-name"?: boolean;\n'
                   '  [key: string]: unknown;\n}\n')


def test_an_agents_sign_in_over_http_redirects_to_its_link_and_takes_its_code_once(signing_agent, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    call = api_server(tmp_path, monkeypatch)
    try:
        status, _, headers = call("GET", "/api/agents/a/sign-in")  # a link the page follows: no fetch
        assert (status, headers["Location"]) == (302, "https://claude.com/x?a=1")
        assert call("POST", "/api/agents/a/sign-in", {"code": "good"})[:2] == (200, {})
        assert call("POST", "/api/agents/a/sign-in", {"code": "good"})[:2] == (409, {"error": "no sign-in under way: start it again"})
        assert call("GET", "/api/agents/a/sign-in-status")[0] == 400  # it declares no sign-in check
        (tmp_path / "agents/a/agent.json").write_text(json.dumps({"signedIn": ["cli"]}))
        signing_agent.write_text("#!/bin/sh\nexit 0\n")
        assert call("GET", "/api/agents/a/sign-in-status")[:2] == (200, {"signedIn": True})
    finally:
        call.server.shutdown()


def test_an_agents_sign_in_runs_its_after_sign_in_sh_once_signed_in(signing_agent, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    (tmp_path / "agents/a/after-sign-in.sh").write_text('echo "$0" >> "${0%/*}/ran"\n')
    web.sign_in("a")
    with pytest.raises(ValueError, match="Bad code"):
        web.sign_in_code("a", "bad")
    assert not (tmp_path / "agents/a/ran").exists()
    web.sign_in("a")
    web.sign_in_code("a", "good")
    assert (tmp_path / "agents/a/ran").read_text() == f"{tmp_path}/agents/a/after-sign-in.sh\n"


def test_an_agents_sign_in_check_is_its_signed_in_command_exiting_0(signing_agent, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    (tmp_path / "agents/a/agent.json").write_text(json.dumps({"signedIn": ["cli", "status"]}))
    signing_agent.write_text('#!/bin/sh\n[ -e "$0.in" ]\n')
    assert web.signed_in("a") is False
    (tmp_path / "cli.in").touch()
    assert web.signed_in("a") is True
    with pytest.raises(ValueError, match="has no sign-in check"):
        web.signed_in("b")


def test_an_agents_sign_in_finds_its_cli_in_local_bin_off_the_path(signing_agent, tmp_path, monkeypatch):
    (tmp_path / ".local/bin").mkdir(parents=True)
    signing_agent.rename(tmp_path / ".local/bin/cli")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert web.sign_in("a") == "https://claude.com/x?a=1"
    monkeypatch.setenv("HOME", str(tmp_path / "none"))
    with pytest.raises(ValueError, match="cli is not installed on the server"):
        web.sign_in("a")
