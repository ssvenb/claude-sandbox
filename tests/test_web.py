"""web/server.py: chats on pipes and terminals in ptys, streamed to the page; only our own page
may drive it."""
import base64
import json
import os
import re
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

UI = REPO / "web/ui"  # the pages: a React app, built into UI/dist, which the server serves


def build_ui():
    """Makes sure web/ui/dist is there and no older than what it is built from: `npm run build`
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
        pytest.skip("the web UI is not built and there is no npm to build it: `npm ci && npm run build` in web/ui")
    steps = ([] if (UI / "node_modules").exists() else [["npm", "ci"]]) + [["npm", "run", "build"]]
    for step in steps:
        done = subprocess.run(step, cwd=UI, capture_output=True, text=True)
        assert done.returncode == 0, f"{' '.join(step)} in web/ui failed:\n{done.stdout}{done.stderr}"
    return dist


@pytest.fixture(scope="session")
def ui_dist():
    return build_ui()


@pytest.fixture
def ui(tmp_path, ui_dist):
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
    assert web.command("resume", "0a1b2c", None, True) == [str(REPO / "run.sh"), "--resume", "0a1b2c", "--chat"]
    with pytest.raises(ValueError, match="ui must be chat or terminal"):
        web.start("/p", "run", None, None, "tui")
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

def test_the_pages_are_one_built_app_and_what_it_loads_is_served_under_its_own_path(ui):
    page = ui("/").read()
    assert b'<div id="root">' in page and ui("/").headers["Content-Type"].startswith("text/html")
    assert ui("/chat").read() == page and ui("/session").read() == page  # the app picks the page by its path
    assert b"localStorage.getItem('theme')" in page  # the pinned day or night, set before the first paint
    scripts, styles = re.findall(rb'src="(/assets/[^"]+\.js)"', page), re.findall(rb'href="(/assets/[^"]+\.css)"', page)
    assert len(scripts) == 1 and styles
    script = ui(scripts[0].decode())
    assert script.status == 200 and script.headers["Content-Type"].startswith("text/javascript")
    code = script.read()
    assert b"/api/project" in code  # the dashboard; a session's page loads its own part, only where there is one
    for part in (b"Message to the agent", b"xterm"):  # the chat's composer, the terminal's xterm.js
        assert part not in code
        [chunk] = [f.name for f in (UI / "dist/assets").glob("*.js") if part in f.read_bytes()]
        got = ui(f"/assets/{chunk}")
        assert got.status == 200 and got.headers["Content-Type"].startswith("text/javascript") and chunk.encode() in code
    for style in styles:
        got = ui(style.decode())
        assert got.status == 200 and got.headers["Content-Type"].startswith("text/css")


@pytest.mark.parametrize("path", ["/server.py", "/../server.py", "/assets/../../server.py", "/../../run.sh", "/index.html",
                                  "/assets/nope.js", "/%2e%2e/server.py", "/assets", "/ui/package.json", "/package.json"])
def test_only_what_the_build_made_for_the_pages_is_served(ui, path):
    assert ui(path).status == 404


def test_without_a_build_the_pages_say_how_to_make_one(tmp_path):
    shutil.copytree(REPO / "web", tmp_path / "web", ignore=shutil.ignore_patterns("__pycache__", "ui"))
    proc = subprocess.Popen([tmp_path / "web/server.py", "--port", "0", "--projects", tmp_path / "projects"],
                            stdout=subprocess.PIPE, text=True, env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
    try:
        base = proc.stdout.readline().split()[1]
        for page in ("/", "/chat", "/session"):
            with pytest.raises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(base + page, timeout=10)
            assert e.value.code == 503 and e.value.headers["Content-Type"].startswith("text/plain")
            assert "npm ci && npm run build" in e.value.read().decode()
        assert json.load(urllib.request.urlopen(base + "/api/state", timeout=10))["sessions"] == []  # the API is there all the same
    finally:
        proc.terminate()
        proc.wait(5)


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


def test_a_projects_settings_are_read_and_saved_to_its_claude_sandbox_json(ui):
    file = ui.tmp / "proj/.claude-sandbox.json"
    got = json.load(ui("/api/config?project=" + ui.project))
    assert (got["file"], got["exists"], got["config"]) == (str(file), False, {})
    kvm = next(p for p in got["plugins"] if p["name"] == "kvm")  # every plugin, as its manifest says
    assert kvm["defaultEnabled"] is False and kvm["description"] and "briefing" in kvm["example"]
    assert [s["key"] for s in kvm["settings"]] == ["briefing"]  # the settings it declares
    assert any(s["env"] == "AGENT" for s in got["kernel"]["settings"])  # and the sandbox's own
    claude = next(a for a in got["agents"] if a["name"] == "claude")
    assert any(s["env"] == "CLAUDE_EFFORT" for s in claude["settings"])

    config = {"env": {"CLAUDE_EFFORT": "high"}, "plugins": {"kvm": {"enabled": True, "briefing": "VMs"}},
              "mine": [1]}  # whatever else the file holds is the page's to keep
    saved = json.load(ui("/api/config", json.dumps({"project": ui.project, "config": config}).encode()))
    assert saved["exists"] and saved["config"] == config == json.loads(file.read_text())
    assert file.read_text().endswith("}\n") and list((ui.tmp / "proj").iterdir()) == [file]

    for bad in ([], {"plugins": []}, {"plugins": {"kvm": "on"}}, {"plugins": {"kvm": {"enabled": "maybe"}}},
                {"env": {"AGENT": ["claude"]}},
                # declared settings are checked against their type
                {"env": {"CLAUDE_EFFORT": "huge"}}, {"env": {"AGENT_WORKSPACE_CLEANUP": "yes"}},
                {"env": {"PORTS": "80,443"}}, {"plugins": {"project-deps": {"apt": "ripgrep"}}},
                {"plugins": {"dev-server": {"command": ["make"]}}},
                {"plugins": {"upstream-proxy": {"routes": [{"name": "a", "upstream": "https://x"}]}}},
                {"plugins": {"upstream-proxy": {"routes": [{"name": "a", "port": 70000, "upstream": "https://x"}]}}},
                {"plugins": {"upstream-proxy": {"routes": [{"name": "a", "port": 1, "upstream": "https://x",
                                                            "auth": {"type": "bearer"}}]}}}):
        assert ui("/api/config", json.dumps({"project": ui.project, "config": bad}).encode()).status == 400
    assert json.loads(file.read_text()) == config  # none of them touched it
    assert ui("/api/config", json.dumps({"project": "/etc", "config": {}}).encode()).status == 400
    assert ui("/api/config?project=/etc").status == 404
    assert ui("/api/config", json.dumps({"project": ui.project, "config": {}}).encode(),
              Origin="http://evil.example").status == 403

    file.write_text("{not json")  # not ours to overwrite: fixed by hand first
    assert "not valid JSON" in json.load(ui("/api/config?project=" + ui.project))["error"]


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
    stopped = web.start(str(tmp_path), "resume", "0a1b2c", ui="terminal")
    deleted = web.start(str(tmp_path), "resume", "3d4e5f", ui="terminal")
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
    s = web.start(str(tmp_path), "resume", "0a1b2c", ui="terminal")

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
           ui="terminal", status=lambda: None)
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
    for s in started:
        s.stop()
    for s in started:
        s.proc.wait(5)
    web.sessions.clear()


def test_prompts_typed_while_the_sandbox_starts_wait_and_reach_the_agent_in_order(chat, monkeypatch):
    monkeypatch.setenv("STUB_BOOT", "0.2")
    s = chat(task="first, please")  # a task is simply the first message
    assert (s.ui, s.status(), s.json()["title"]) == ("chat", "starting", "first, please")
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


def test_a_prompt_takes_the_images_pasted_into_it(chat, monkeypatch):
    monkeypatch.setenv("STUB_BOOT", "0.2")
    picture = {"type": "image/png", "data": PNG}
    s = web.start(str(chat.tmp), "run", None, None, None, [picture])  # a first message of only a picture
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
        with pytest.raises(ValueError):
            web.start(str(chat.tmp), "run", None, "look", "terminal", [picture])
    finally:
        s.stop()
        s.proc.wait(5)


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
        s.proc.wait(5)


def test_a_chat_streams_its_events_and_takes_answers_and_interrupts(chat, tmp_path):
    (tmp_path / "projects").write_text(f"{tmp_path}\n")
    server = web.serve(0, tmp_path / "projects")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def post(path, body=None, origin=base):
        req = urllib.request.Request(base + path, json.dumps(body or {}).encode(), headers={"Origin": origin})
        try:
            return urllib.request.urlopen(req, timeout=5).status
        except urllib.error.HTTPError as e:
            return e.code
    try:
        s = json.load(urllib.request.urlopen(urllib.request.Request(base + "/api/sessions", json.dumps(
            {"project": str(tmp_path), "kind": "run"}).encode())))
        assert s["ui"] == "chat" and s["status"] == "starting"
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
        assert post(f"/api/sessions/{s['id']}/prompt", {"text": "ask me"}) == 200
        asked = read(lambda e: e["type"] == "ask")
        assert read(lambda e: e["type"] == "status")["state"] == "question"
        assert post(f"/api/sessions/{s['id']}/answer", {"id": asked["id"], "answers": {"Which database?": "SQLite"}}) == 200
        assert read(lambda e: e["type"] == "text" and e["id"] == "a1")["text"] == "Going with **SQLite**."
        with web.lock:  # the answer is kept with its question, for a page opened later
            assert [(e["answers"], e.get("done")) for e in live.events if e["type"] == "ask"] == [
                ({"Which database?": "SQLite"}, True)]
        read(lambda e: e["type"] == "status" and e["state"] == "idle")

        assert post(f"/api/sessions/{s['id']}/prompt", {"text": "a long one"}) == 200
        read(lambda e: e["type"] == "tool" and e["name"] == "Bash")
        assert live.json()["activity"] == "Bash: Wait a long time"
        assert post(f"/api/sessions/{s['id']}/interrupt") == 200
        assert read(lambda e: e["type"] == "result" and e["id"] == "b2")["error"] is True
        assert post(f"/api/sessions/{s['id']}/model", {"id": "opus"}) == 200
        assert read(lambda e: e["type"] == "model")["id"] == "opus"

        assert post(f"/api/sessions/{s['id']}/prompt", {"text": "  "}) == 400          # not a message
        assert post(f"/api/sessions/{s['id']}/input") == 400                           # a chat has no keys
        assert urllib.request.urlopen(f"{base}/api/sessions/{s['id']}/stream", timeout=5).status == 0
    except urllib.error.HTTPError as e:
        assert e.code == 400  # nor a terminal's stream
        assert post(f"/api/sessions/{s['id']}/prompt", {"text": "x"}, "http://evil.example") == 403  # nor another site's page
    finally:
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


def test_sync_pulls_installs_and_restarts_only_under_systemd(monkeypatch):
    ran, spawned = [], []
    monkeypatch.setattr(web.subprocess, "run", lambda step, **_: ran.append(step) or subprocess.CompletedProcess(step, 0, "", ""))
    monkeypatch.setattr(web.subprocess, "Popen", lambda cmd, **_: spawned.append(cmd))
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    assert web.sync() == {"restarting": False} and not spawned
    assert ran[0][-4:] == ["pull", "--ff-only", "origin", "main"] and ran[1][-1].endswith("install.sh") and ran[1][1] == "-ic"
    monkeypatch.setenv("INVOCATION_ID", "x")
    assert web.sync() == {"restarting": True} and web.SERVICE in spawned[0][-1]
    monkeypatch.setattr(web.subprocess, "run", lambda step, **_: subprocess.CompletedProcess(step, 1, "", "not a fast-forward"))
    with pytest.raises(ValueError, match="not a fast-forward"):
        web.sync()
