"""web/server.py: sessions in ptys, streamed to the page; only our own page may drive it."""
import base64
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

from conftest import REPO

sys.path.insert(0, str(REPO / "web"))
import server as web  # noqa: E402


@pytest.fixture
def ui(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    listing = tmp_path / "projects"
    listing.write_text(f"# comment\n\n{project}\n")
    proc = subprocess.Popen([REPO / "web/server.py", "--port", "0", "--projects", listing,
                             ], stdout=subprocess.PIPE, text=True,
                            env={"PATH": f"{tmp_path}/bin:/usr/bin:/bin", "SHELL": "/bin/sh", "HOME": str(tmp_path)})
    base = proc.stdout.readline().split()[1]

    def call(path, body=None, **headers):
        req = urllib.request.Request(base + path, data=body, headers=headers)
        try:
            return urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as e:
            return e
    call.project, call.tmp = str(project), tmp_path
    yield call
    proc.terminate()
    proc.wait(5)


def test_a_projects_terminal_runs_there_streams_and_is_one_per_project(ui):
    assert json.load(ui("/api/state"))["projects"] == [ui.project]
    ask = {"project": ui.project, "kind": "shell"}
    s = json.load(ui("/api/sessions", json.dumps(ask).encode()))
    assert json.load(ui("/api/sessions", json.dumps(ask).encode()))["id"] == s["id"]  # one per project
    assert ui(f"/api/sessions/{s['id']}/resize?cols=100&rows=30", b"").status == 200
    ui(f"/api/sessions/{s['id']}/input", b"echo $(basename $PWD)-$((40+2)); exit 3\n")
    seen, events = b"", ui(f"/api/sessions/{s['id']}/stream")
    for line in events:
        if line.startswith(b"data: ") and line != b"data: x\n":
            seen += base64.b64decode(line[6:])
        if line.startswith(b"event: exit"):
            break
    assert b"proj-42" in seen
    [ended] = json.load(ui("/api/state"))["sessions"]  # kept, so its tab can show how it ended
    assert (ended["id"], ended["exit"]) == (s["id"], 3)
    again = json.load(ui("/api/sessions", json.dumps(ask).encode()))  # the next one replaces it
    assert [x["id"] for x in json.load(ui("/api/state"))["sessions"]] == [again["id"]] != [s["id"]]
    ui(f"/api/sessions/{again['id']}/stop", b"")  # stops it, and keeps it listed
    for _ in range(50):
        if json.load(ui("/api/state"))["sessions"][0]["exit"] is not None:
            break
        time.sleep(0.1)
    assert [x["id"] for x in json.load(ui("/api/state"))["sessions"]] == [again["id"]]
    ui(f"/api/sessions/{again['id']}/delete", b"")  # and, ended, removes it
    assert json.load(ui("/api/state"))["sessions"] == []


@pytest.mark.parametrize("body, headers, status", [
    ({"project": "/etc", "kind": "shell"}, {}, 400),                       # not a configured project
    ({"kind": "resume", "run_id": "x; rm -rf"}, {}, 400),                  # not a run id
    ({"kind": "shell"}, {"Origin": "http://evil.example"}, 403),           # another site's page
    ({"kind": "shell"}, {"Host": "evil.example"}, 403),                    # DNS rebinding
])
def test_requests_that_must_not_start_anything(ui, body, headers, status):
    body = {"project": ui.project, **body}
    assert ui("/api/sessions", json.dumps(body).encode(), **headers).status == status
    assert json.load(ui("/api/state"))["sessions"] == []


def test_sandbox_sessions_run_run_sh_under_an_id_the_ui_knows():
    assert web.command("run", "0a1b2c") == [str(REPO / "run.sh"), "--run-id", "0a1b2c"]
    assert web.command("resume", "0a1b2c") == [str(REPO / "run.sh"), "--resume", "0a1b2c"]
    assert web.command("run", "0a1b2c", "Fix #7") == [str(REPO / "run.sh"), "--run-id", "0a1b2c",
                                                       "--task", "Fix #7"]
    for kind, run_id, task in (("shell", None, "x"), ("resume", "0a1b2c", "x"), ("run", None, 7),
                               ("run", None, "  ")):
        with pytest.raises(ValueError, match="a task starts a new run"):
            web.start("/p", kind, run_id, task)


def test_a_projects_line_may_be_a_glob(tmp_path):
    code = tmp_path / "code"
    for name in ("beta", "alpha", "plain"):
        (code / name).mkdir(parents=True)
    (code / "alpha/.git").mkdir()
    (code / "beta/.git").write_text("gitdir: elsewhere\n")  # a worktree's .git is a file
    (code / "notes.txt").write_text("")
    listing = tmp_path / "projects"
    listing.write_text(f"# all of them\n{code}/*\n\n{code}/*/.git\n{tmp_path}/missing-*\n")
    every = [str(code / d) for d in ("alpha", "beta", "plain")]
    assert web.projects(listing) == every  # files skipped, repeats listed once, no match → nothing
    listing.write_text(f"{code}/*/.git\n{code}/plain\n")
    assert web.projects(listing) == [str(code / "alpha"), str(code / "beta"), str(code / "plain")]


def test_a_network_bind_admits_this_machines_own_names_only():
    names = web.local_names("0.0.0.0")
    assert {"127.0.0.1", "localhost", web.socket.gethostname()} <= names
    assert "evil.example" not in names
    assert web.local_names("127.0.0.1") == {"127.0.0.1", "localhost"}


def test_sessions_publish_their_ports_where_the_page_listens():
    assert web.ports_bind("0.0.0.0", {}) == "0.0.0.0"
    assert web.ports_bind("", {}) == "0.0.0.0"
    assert web.ports_bind("192.168.1.5", {}) == "192.168.1.5"
    assert web.ports_bind("127.0.0.1", {}) is None  # run.sh's own default: loopback
    assert web.ports_bind("0.0.0.0", {"PORTS_BIND": "10.0.0.2"}) == "10.0.0.2"  # the shell's says otherwise


def test_allow_host_adds_a_name_to_the_allowlist(tmp_path):
    server = web.serve(0, tmp_path / "projects", allow_hosts=["box.vpn.example"])
    try:
        port = server.server_address[1]
        assert {f"box.vpn.example:{port}", f"127.0.0.1:{port}"} <= server.hosts
        assert f"evil.example:{port}" not in server.hosts
    finally:
        server.server_close()

def test_the_session_page_is_served_next_to_the_status_page(ui):
    assert b"/api/project" in ui("/").read()
    assert b"/stream" in ui("/session").read()


# Stands in for `code serve-web`: echoes each request's head back as the response body.
FAKE_CODE = r"""#!/usr/bin/env python3
import socket, sys
args = sys.argv[1:]
assert args[0] == "serve-web" and "--without-connection-token" in args and "--server-data-dir" in args
s = socket.socket(socket.AF_UNIX)
s.bind(args[args.index("--socket-path") + 1])
s.listen()
while True:
    c, _ = s.accept()
    head = b""
    while b"\r\n\r\n" not in head:
        head += c.recv(65536)
    c.sendall(b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n" + head)
    c.close()
"""


def test_vscode_opens_only_a_sessions_checkout_through_the_guarded_tunnel(ui):
    ask = lambda sid: ui("/api/vscode", json.dumps({"session": sid}).encode())  # noqa: E731
    json.load(ui("/api/project?project=" + ui.project))  # agent-workspace: checkouts in ~/.agent-workspaces
    mirror = ui.tmp / ".agent-workspaces/proj-20261112-0a1b2c"
    mirror.mkdir(parents=True)
    # run.sh itself fails here (no App key), but the session keeps its run id, as an ended run does.
    s = json.load(ui("/api/sessions", json.dumps({"project": ui.project, "kind": "resume",
                                                  "run_id": "0a1b2c"}).encode()))
    assert s["workspace"] == str(mirror)
    assert "not installed" in json.load(ask(s["id"]))["error"]
    assert ui("/vscode/?folder=/x").status == 502  # nothing started yet
    code = ui.tmp / "bin/code"
    code.parent.mkdir()
    code.write_text(FAKE_CODE)
    code.chmod(0o755)

    assert json.load(ask(s["id"])) == {"folder": str(mirror)}
    assert json.load(ask(s["id"])) == {"folder": str(mirror)}  # the same server again
    seen = ui("/vscode/?folder=/x").read()
    assert seen.startswith(b"GET /vscode/?folder=/x HTTP/1.1\r\n") and b"Connection: close" in seen
    assert ui("/vscode/", b"body").read().startswith(b"POST /vscode/ ")
    # VS Code in a browser is a shell on this machine: our own page only.
    assert ui("/vscode/", Origin="http://evil.example").status == 403
    assert ui("/vscode/", Host="evil.example").status == 403
    assert ui("/vscodex").status == 404

    assert ask("nosuchid").status == 400
    assert ui("/api/vscode", json.dumps({"project": ui.project}).encode()).status == 400  # projects: no


def test_the_page_gets_what_the_projects_plugins_describe(ui):
    # No plugin of this bare directory has anything to list, but the answer is run.sh's own.
    said = json.load(ui("/api/project?project=" + ui.project))
    assert said["lists"] == [] and said["agent"] == "claude" and "git-workspace" in said["plugins"]
    assert ui("/api/project?project=/etc").status == 404


def test_a_runs_checkout_is_found_where_a_plugin_says_it_is(tmp_path, monkeypatch):
    (tmp_path / "proj-20261112-0a1b2c").mkdir()
    monkeypatch.setitem(web.described, "/proj", {"checkout": f"{tmp_path}/*-{{run_id}}"})
    assert web.checkout("/proj", "0a1b2c") == str(tmp_path / "proj-20261112-0a1b2c")
    assert web.checkout("/proj", "ffffff") is None and web.checkout("/proj", None) is None
    assert web.checkout("/other", "0a1b2c") is None  # no plugin of that project keeps one


def test_a_project_run_sh_cannot_describe_says_why(tmp_path):
    (tmp_path / ".claude-sandbox.json").write_text("{not json")
    [note] = web.describe(str(tmp_path))["notes"]
    assert ".claude-sandbox.json" in note


def test_vscode_skips_the_desktop_launcher_for_the_cli_it_bundles(tmp_path, monkeypatch):
    def exe(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755)
        return path
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    with pytest.raises(ValueError, match="not installed"):
        web.vscode_cli()
    standalone = exe(tmp_path / "bin/code")
    assert web.vscode_cli() == str(standalone)  # the standalone CLI serves itself
    # .deb/.rpm: /usr/bin/code links to /usr/share/code/bin/code, next to the bundled CLI
    standalone.unlink()
    (tmp_path / "bin/code").symlink_to(exe(tmp_path / "share/code/bin/code"))
    bundled = exe(tmp_path / "share/code/bin/code-tunnel")
    assert web.vscode_cli() == str(bundled)
    # snap: <snap>/bin/code links to /usr/bin/snap; the CLI is in the snap's own tree
    (tmp_path / "bin/code").unlink()
    (tmp_path / "bin/code").symlink_to(exe(tmp_path / "usr/bin/snap"))
    bundled = exe(tmp_path / "code/current/usr/share/code/bin/code-tunnel")
    assert web.vscode_cli() == str(bundled)


def test_vscode_that_will_not_start_says_what_it_printed(tmp_path, monkeypatch):
    code = tmp_path / "bin/code"
    code.parent.mkdir()
    code.write_text("#!/bin/sh\necho starting\necho 'error: no such option --socket-path' >&2\nexit 2\n")
    code.chmod(0o755)
    monkeypatch.setenv("PATH", str(code.parent))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(web, "vscode_server", None)
    with pytest.raises(ValueError, match=r"exited with 2: error: no such option --socket-path"):
        web.vscode()
    run_dir = os.path.dirname(web.vscode_server[1])
    with pytest.raises(ValueError):  # a second try starts afresh, and clears the failed one away
        web.vscode()
    assert not os.path.exists(run_dir)
    shutil.rmtree(os.path.dirname(web.vscode_server[1]))


def test_vscode_settings_are_applied_over_the_ones_already_there(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    file = tmp_path / "claude-sandbox/vscode/data/Machine/settings.json"
    assert web.vscode_data() == tmp_path / "claude-sandbox/vscode"
    assert json.loads(file.read_text()) == {"chat.disableAIFeatures": True}
    file.write_text('{"editor.fontSize": 15, "chat.disableAIFeatures": false}')
    web.vscode_data()
    assert json.loads(file.read_text()) == {"editor.fontSize": 15, "chat.disableAIFeatures": True}
    file.write_text('{\n  // mine\n  "editor.fontSize": 15\n}')
    web.vscode_data()  # with comments it is left as it is
    assert "// mine" in file.read_text()


def test_a_session_outlives_its_tabs_until_stopped_or_deleted(tmp_path, monkeypatch):
    docker = tmp_path / "docker"
    docker.write_text(f'#!/bin/sh\necho "$*" >>"{tmp_path}/docker-calls"\n')
    docker.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    monkeypatch.setattr(web, "command", lambda *_: ["sleep", "30"])
    monkeypatch.setattr(web, "KEEPALIVE", 0.2)
    (tmp_path / "projects").write_text(f"{tmp_path}\n")
    server = web.serve(0, tmp_path / "projects")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    post = lambda path: urllib.request.urlopen(urllib.request.Request(  # noqa: E731
        base + path, b"", headers={"Origin": base}), timeout=5)
    stopped = web.start(str(tmp_path), "resume", "0a1b2c")
    deleted = web.start(str(tmp_path), "resume", "3d4e5f")
    try:
        urllib.request.urlopen(f"{base}/api/sessions/{stopped.id}/stream", timeout=5).close()
        for _ in range(10):  # a few keepalives: the closed tab is long noticed
            time.sleep(0.1)
        assert (stopped.exit, stopped.listeners) == (None, [])  # the tab is let go, the session runs on

        post(f"/api/sessions/{stopped.id}/stop")
        post(f"/api/sessions/{deleted.id}/delete")  # still running: stopped first
        calls = tmp_path / "docker-calls"
        for _ in range(50):
            if None not in (stopped.exit, deleted.exit) and len(calls.read_text().splitlines()) == 2:
                break
            time.sleep(0.1)
        assert sorted(calls.read_text().splitlines()) == ["rm -f sandbox-0a1b2c", "rm -f sandbox-3d4e5f"]
        assert list(web.sessions) == [stopped.id]  # the stopped one stays listed, to read and resume
        with pytest.raises(OSError):
            os.fstat(deleted.fd)  # its pty closed once it had ended
    finally:
        stopped.stop()
        deleted.stop()
        server.shutdown()
        web.sessions.clear()


def marker(state):
    return b"\x1b]1337;SetUserVar=agent_status=" + base64.b64encode(state.encode()) + b"\x07"


def test_a_sessions_status_is_what_its_agent_last_said_else_whether_output_flows(tmp_path, monkeypatch):
    out = tmp_path / "out"
    script = tmp_path / "agent"
    # Says each line of `out` it is given, raw: the agent-status hook's marker among other output,
    # the second one split over two writes.
    script.write_text("#!/bin/sh\nstty -echo\nwhile read f; do cat \"$f\"; done\n")
    script.chmod(0o755)
    monkeypatch.setattr(web, "command", lambda *_: [str(script)])
    s = web.start(str(tmp_path), "resume", "0a1b2c")

    def says(*chunks, then):
        for chunk in chunks:
            seen = len(s.buf)
            out.write_bytes(chunk)
            s.write(f"{out}\n".encode())
            for _ in range(100):  # until the agent has said all of it
                if len(s.buf) >= seen + len(chunk):
                    break
                time.sleep(0.05)
        assert s.status() == then, bytes(s.buf)

    try:
        assert s.status() == "working"  # nothing said yet, and its output just started
        s.output -= web.QUIET
        assert s.status() == "idle"  # quiet: nothing to do
        says(b"text " + marker("question") + b" more", then="question")
        m = marker("idle")
        says(m[:9], m[9:], then="idle")
        says(marker("bogus"), marker("working"), then="working")
        s.output -= web.STALE + 1  # working, yet silent this long: it was interrupted
        assert s.status() == "idle"
        assert s.json()["status"] == "idle"
    finally:
        s.stop()
        for _ in range(50):
            if s.exit is not None:
                break
            time.sleep(0.1)
        web.sessions.clear()
    assert s.status() is None  # ended


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
    the marker the server reads; it never prints anything or fails the agent's tool call."""
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
    found = web.STATUS.findall(got)
    assert [base64.b64decode(f) for f in found] == ([said] if said else [])
    assert got.endswith(b"rc=0\r\n")


def test_deleting_tidies_up_only_what_a_plugin_offered_for_that_run(tmp_path, monkeypatch):
    """offers(): the run's items with an on_delete, none while another session of the run is
    listed; tidy(): runs `run.sh --web-action` for those of them the page's user said yes to."""
    from types import SimpleNamespace as NS
    log = tmp_path / "actions"
    run_sh = tmp_path / "run.sh"
    run_sh.write_text(f'#!/bin/sh\necho "$*" >>"{log}"\n[ "$4" != 9 ] || {{ echo "❌ gh pr close: gone" >&2; exit 1; }}\n')
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
    assert log.read_text() == "--web-action github-auth close-pr 3\n"
    assert web.tidy(s, ["u9"], offered) == ["#9: ❌ gh pr close: gone"]


def test_a_running_sessions_live_items_are_read_afresh_on_every_poll(tmp_path, monkeypatch):
    """web_live_items: a file a plugin keeps current (the central port proxy's published ports),
    re-read for each running session; an ended session, or a terminal, shows none."""
    from types import SimpleNamespace as NS
    live = tmp_path / "items.json"
    monkeypatch.setitem(web.described, str(tmp_path), {"lists": [], "live": [str(live), str(tmp_path / "none")]})
    assert web.live_items(str(tmp_path), "0a1b2c") == []  # nothing published yet
    port = {"run_id": "0a1b2c", "ref": ":3000", "url": "http://{host}:3000/", "title": "Port 3000"}
    live.write_text(json.dumps([port, {"run_id": "ffffff", "ref": ":3000", "url": "x"}, "junk"]))
    assert web.live_items(str(tmp_path), "0a1b2c") == [port]
    assert web.live_items(str(tmp_path), None) == []
    s = NS(project=str(tmp_path), run_id="0a1b2c", exit=None, kind="resume", id="a", started=0,
           status=lambda: None)
    assert web.Session.json(s)["items"] == [port]
    s.exit = 0
    assert web.Session.json(s)["items"] == []
