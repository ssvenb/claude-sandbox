"""web/server.py: sessions in ptys, streamed to the page; only our own page may drive it."""
import base64
import json
import subprocess
import sys
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


def test_a_shell_session_runs_in_the_project_and_streams_its_output(ui):
    assert json.load(ui("/api/state"))["projects"] == [ui.project]
    s = json.load(ui("/api/sessions", json.dumps({"project": ui.project, "kind": "shell"}).encode()))
    assert ui(f"/api/sessions/{s['id']}/resize?cols=100&rows=30", b"").status == 200
    ui(f"/api/sessions/{s['id']}/input", b"echo $(basename $PWD)-$((40+2)); exit 3\n")
    seen, events = b"", ui(f"/api/sessions/{s['id']}/stream")
    for line in events:
        if line.startswith(b"data: ") and line != b"data: x\n":
            seen += base64.b64decode(line[6:])
        if line.startswith(b"event: exit"):
            break
    assert b"proj-42" in seen
    [ended] = json.load(ui("/api/state"))["sessions"]
    assert ended["exit"] == 3
    ui(f"/api/sessions/{s['id']}/close", b"")
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

def test_the_session_page_is_served_next_to_the_status_page(ui):
    assert b"/api/project" in ui("/").read()
    assert b"/stream" in ui("/session").read()


# Stands in for `code serve-web`: echoes each request's head back as the response body.
FAKE_CODE = r"""#!/usr/bin/env python3
import socket, sys
args = sys.argv[1:]
assert args[0] == "serve-web" and "--without-connection-token" in args
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


def test_vscode_is_started_once_and_reached_only_through_the_guarded_tunnel(ui):
    ask = lambda **body: ui("/api/vscode", json.dumps(body).encode())  # noqa: E731
    assert "not installed" in json.load(ask(project=ui.project))["error"]
    assert ui("/vscode/?folder=/x").status == 502  # nothing started yet
    code = ui.tmp / "bin/code"
    code.parent.mkdir()
    code.write_text(FAKE_CODE)
    code.chmod(0o755)

    assert json.load(ask(project=ui.project)) == {"folder": ui.project}
    assert json.load(ask(project=ui.project)) == {"folder": ui.project}  # the same server again
    seen = ui("/vscode/?folder=/x").read()
    assert seen.startswith(b"GET /vscode/?folder=/x HTTP/1.1\r\n") and b"Connection: close" in seen
    assert ui("/vscode/", b"body").read().startswith(b"POST /vscode/ ")
    # VS Code in a browser is a shell on this machine: our own page only.
    assert ui("/vscode/", Origin="http://evil.example").status == 403
    assert ui("/vscode/", Host="evil.example").status == 403
    assert ui("/vscodex").status == 404

    assert ask(project="/etc").status == 400
    s = json.load(ui("/api/sessions", json.dumps({"project": ui.project, "kind": "shell"}).encode()))
    assert s["workspace"] is None and ask(session=s["id"]).status == 400  # a shell has no checkout


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

def test_the_session_page_is_served_next_to_the_status_page(ui):
    assert b"/api/project" in ui("/").read()
    assert b"/stream" in ui("/session").read()


# Stands in for `code serve-web`: echoes each request's head back as the response body.
FAKE_CODE = r"""#!/usr/bin/env python3
import socket, sys
args = sys.argv[1:]
assert args[0] == "serve-web" and "--without-connection-token" in args
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


def test_vscode_is_started_once_and_reached_only_through_the_guarded_tunnel(ui):
    ask = lambda **body: ui("/api/vscode", json.dumps(body).encode())  # noqa: E731
    assert "not installed" in json.load(ask(project=ui.project))["error"]
    assert ui("/vscode/?folder=/x").status == 502  # nothing started yet
    code = ui.tmp / "bin/code"
    code.parent.mkdir()
    code.write_text(FAKE_CODE)
    code.chmod(0o755)

    assert json.load(ask(project=ui.project)) == {"folder": ui.project}
    assert json.load(ask(project=ui.project)) == {"folder": ui.project}  # the same server again
    seen = ui("/vscode/?folder=/x").read()
    assert seen.startswith(b"GET /vscode/?folder=/x HTTP/1.1\r\n") and b"Connection: close" in seen
    assert ui("/vscode/", b"body").read().startswith(b"POST /vscode/ ")
    # VS Code in a browser is a shell on this machine: our own page only.
    assert ui("/vscode/", Origin="http://evil.example").status == 403
    assert ui("/vscode/", Host="evil.example").status == 403
    assert ui("/vscodex").status == 404

    assert ask(project="/etc").status == 400
    s = json.load(ui("/api/sessions", json.dumps({"project": ui.project, "kind": "shell"}).encode()))
    assert s["workspace"] is None and ask(session=s["id"]).status == 400  # a shell has no checkout
