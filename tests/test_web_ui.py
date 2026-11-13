"""web/index.html and web/session.html in a real browser: tabs, closing, favicons, CI marks.

The server and its pages run from a copy of web/, next to a stub run.sh: `--web` answers with the
JSON below (what the plugins would describe, tested on their own in test_plugin_hosts.py), and a
session is an "agent" that says it has a question (as the agent-status hook would), waits for a
line, then exits 4; `--web-action` is logged to `actions`. `docker` does nothing (stopping a session
removes its container), `code` is the stand-in from test_web.py. Skipped without Playwright (pip install playwright, then
`python -m playwright install chromium`, or a chromium on the PATH).
"""
import json
import os
import shutil
import subprocess
import urllib.request

import pytest

from conftest import REPO
from test_web import FAKE_CODE

sync_api = pytest.importorskip("playwright.sync_api")

RUN = "abc123"  # the run the fixture's first pull request and checkout belong to

RUN_SH = """#!/bin/sh
case "$1" in
  --web) cat "$(dirname "$0")/web.json" ;;
  --web-action) echo "$2 $3 $4" >>"$(dirname "$0")/actions"; echo '{}' ;;
  *) echo "agent $2 at work${4:+ on: $4}"
     printf '\033]1337;SetUserVar=agent_status=%s\007' "$(printf question | base64)"
     read line; exit 4 ;;
esac
"""
DOCKER = "#!/bin/sh\n"


def tool(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except sync_api.Error:
            exe = shutil.which("chromium") or shutil.which("chromium-browser")
            if not exe:
                pytest.skip("no browser: run `python -m playwright install chromium`")
            b = p.chromium.launch(executable_path=exe)
        yield b
        b.close()


@pytest.fixture
def board(tmp_path, browser):
    sandbox = tmp_path / "sandbox"
    shutil.copytree(REPO / "web", sandbox / "web", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(REPO / "plugins", sandbox / "plugins")
    shutil.copy(REPO / ".claude-sandbox.example.json", sandbox)
    tool(sandbox / "run.sh", RUN_SH)
    tool(tmp_path / "bin/docker", DOCKER)
    tool(tmp_path / "bin/code", FAKE_CODE)
    project = tmp_path / "proj"
    project.mkdir()
    checkout = tmp_path / f"mirrors/proj-20261112-{RUN}"
    checkout.mkdir(parents=True)
    (tmp_path / "projects").write_text(f"{project}\n")
    proc = subprocess.Popen([sandbox / "web/server.py", "--port", "0", "--projects", tmp_path / "projects"],
                            stdout=subprocess.PIPE, text=True,
                            env={"PATH": f"{tmp_path}/bin:/usr/bin:/bin", "HOME": str(tmp_path),
                                 "SHELL": "/bin/sh", "XDG_DATA_HOME": str(tmp_path / "data")})
    base = proc.stdout.readline().split()[1]
    # Items on another origin, as GitHub's are: localhost is the same server, another origin.
    elsewhere = base.replace("127.0.0.1", "localhost")
    (sandbox / "web.json").write_text(json.dumps({"notes": [], "checkout": f"{tmp_path}/mirrors/*-{{run_id}}",
        "live": [str(tmp_path / "ports.json")],
        "session_items": [{"run_id": RUN, "ref": "preview", "title": "The run's preview", "url": f"{elsewhere}/preview"}],
        "run_items": [
            {"ref": "#3", "title": "Agent's work", "url": f"{elsewhere}/pr/3", "run_id": RUN,
             "status": "fail", "status_text": "CI: 1 of 2 checks failed",
             "on_delete": {"plugin": "github-auth", "action": "close-pr", "arg": "3", "ask": "Close #3 too?"}},
            {"ref": "#2", "title": "Went in", "url": f"{elsewhere}/pr/2", "run_id": RUN,
             "note": "Merged", "status": "done", "status_text": "Merged"},
            {"ref": "#4", "title": "By hand", "url": f"{elsewhere}/pr/4", "status": "ok", "status_text": "CI: 2 checks passed",
             "on_delete": {"plugin": "github-auth", "action": "close-pr", "arg": "4", "ask": "Close #4 too?"}}],
        "lists": [
        {"title": "Issues", "items": [{"ref": "#7", "title": "A bug", "url": f"{elsewhere}/issues/7",
                                       "start": {"label": "Resolve", "task": "Fix issue #7 now"}}]}]}))

    context = browser.new_context()
    page = context.new_page()
    answers = page.answers = []  # what to say to the "Close #3 too?" questions, in turn: yes if none left
    asked = page.asked = []

    def dialog(d):
        if d.message.startswith("Close "):
            asked.append(d.message)
            return d.accept() if not answers or answers.pop(0) else d.dismiss()
        d.accept()  # the "Stop …?" confirmations
    page.on("dialog", dialog)
    page.goto(base)
    page.wait_for_selector("a .num")
    page.actions = sandbox / "actions"

    def resume():
        """A session of RUN, the way the PR's Resume button starts one."""
        req = urllib.request.Request(base + "/api/sessions", json.dumps(
            {"project": str(project), "kind": "resume", "run_id": RUN}).encode())
        s = json.load(urllib.request.urlopen(req))
        page.wait_for_selector("button.session")
        return s
    page.resume = resume
    page.base, page.checkout, page.ports = base, checkout, tmp_path / "ports.json"
    page.project = project
    yield page
    context.close()
    proc.terminate()
    proc.wait(10)


def opens_tab(page, click):
    """The page a click opens, after it has loaded."""
    with page.context.expect_page() as new:
        click()
    tab = new.value
    tab.wait_for_url(lambda url: url != "about:blank")  # the page fills the new tab after a fetch
    tab.wait_for_load_state()
    return tab


def again_opens_nothing(page, click):
    before = len(page.context.pages)
    click()
    page.wait_for_timeout(500)
    assert len(page.context.pages) == before


def closes(tab, board, within=10):
    """Waits for tab to close. Not wait_for_event("close"): that misses a tab already closed. The
    wait runs on the dashboard, which stays open: Playwright notices a close only while it waits."""
    for _ in range(within * 10):
        if tab.is_closed():
            return
        board.wait_for_timeout(100)
    raise AssertionError(f"{tab.url} still open")


def icon(tab):
    return tab.eval_on_selector("link[rel=icon]", "e => decodeURIComponent(e.href)")


def test_the_dashboard_shows_totals_ci_icon_buttons_and_its_own_icon(board):
    assert board.title() == "Dashboard" and board.inner_text("h1") == "Dashboard"
    assert "<rect" in icon(board)
    for name in ("New session", "Terminal", "Settings"):  # icon buttons: a glyph, named for screen readers
        button = board.query_selector(f"button[aria-label='{name}']")
        assert button.inner_text() == "" and button.query_selector("svg") and button.get_attribute("title")
    board.resume()
    board.wait_for_function("document.querySelector('.totals').innerText.includes('1\\nSessions')")
    totals = board.inner_text(".totals").split()
    assert totals == ["1", "Sessions", "1", "Issues"]  # pull requests: no column, no total
    board.wait_for_selector("a.chip .status")
    failing, merged = board.query_selector_all("a .status")
    assert (failing.get_attribute("class"), failing.inner_text()) == ("status fail", "✕")
    assert (merged.get_attribute("class"), merged.inner_text()) == ("status done", "⇥")
    assert "CI: 1 of 2 checks failed" in board.get_attribute("a:has(.status.fail)", "title")
    assert "Merged: Went in" in board.get_attribute("a:has(.status.done)", "title")


def test_a_session_has_one_tab_with_a_lamp_in_the_colour_of_what_its_agent_does(board):
    board.resume()
    board.wait_for_selector("button.session .lamp.question")  # the stand-in asks: violet
    tab = opens_tab(board, lambda: board.click("button.session"))
    tab.wait_for_selector("text=has a question")
    assert "#c69cff" in icon(tab) and "<circle" in icon(tab)
    again_opens_nothing(board, lambda: board.click("button.session"))

    tab.click(".xterm")
    tab.keyboard.press("Enter")  # the stand-in agent exits 4
    tab.wait_for_selector("text=exited 4")
    tab.wait_for_function("decodeURIComponent(document.querySelector('link[rel=icon]').href).includes('stroke')")
    board.wait_for_selector("button[aria-label='Resume session']")


def test_one_terminal_per_project_on_this_machine(board):
    term = opens_tab(board, lambda: board.click("button[aria-label='Terminal']"))
    term.wait_for_selector("text=terminal")
    assert "<path" in icon(term)
    term.click(".xterm")
    term.keyboard.type("echo $(basename $PWD)-$((40+2))\n")
    term.wait_for_selector("text=proj-42")  # in the project's directory
    again_opens_nothing(board, lambda: board.click("button[aria-label='Terminal']"))
    assert board.inner_text(".totals").startswith("0")  # a terminal is not a session
    assert board.query_selector("button.session") is None

    term.keyboard.type("exit 3\n")
    term.wait_for_selector("text=exited 3")  # still there to read, not closed under you
    assert not term.is_closed()


def test_one_tab_per_item(board):
    issue = opens_tab(board, lambda: board.click("text=A bug"))
    assert issue.url.endswith("/issues/7")
    again_opens_nothing(board, lambda: board.click("text=A bug"))  # GitHub's tab: another origin


def test_pull_requests_show_only_on_their_runs_session_row(board):
    # No session of the run yet: its pull requests show nowhere, and there is no column of them.
    assert board.query_selector("a.chip") is None
    assert board.query_selector("h3:has-text('Pull requests')") is None
    board.resume()
    board.wait_for_selector("button.session ~ a.chip.fail")
    row = board.query_selector("li:has(button.session)")
    assert [c.text_content() for c in row.query_selector_all("a.chip")] == ["✕#3", "⇥#2", "preview"]
    assert "Agent's work" in board.get_attribute("a.chip.fail", "title")
    assert "CI: 1 of 2 checks failed" in board.get_attribute("a.chip.fail", "title")
    assert board.query_selector("a.chip.done")  # the run's merged one, too
    assert board.query_selector("text=By hand") is None  # a pull request of no run: nowhere
    pr = opens_tab(board, lambda: board.click("a.chip.fail"))
    assert pr.url.endswith("/pr/3")
    again_opens_nothing(board, lambda: board.click("a.chip.fail"))
    preview = opens_tab(board, lambda: board.click("a.chip:has-text('preview')"))
    assert preview.url.endswith("/preview")


def test_a_port_the_session_publishes_is_a_button_on_its_row_while_published(board):
    board.resume()
    port = board.base.rsplit(":", 1)[1]
    # As the central port proxy writes it: `{host}` is whatever name the page was opened by.
    board.ports.write_text(json.dumps([{"run_id": RUN, "ref": ":3000", "title": "Port 3000 of the sandbox",
                                        "url": f"http://{{host}}:{port}/published"}]))
    board.wait_for_selector("button.session ~ a.chip:has-text(':3000')")
    assert board.get_attribute("a.chip:has-text(':3000')", "href") == f"{board.base}/published"
    published = opens_tab(board, lambda: board.click("a.chip:has-text(':3000')"))
    assert published.url == f"{board.base}/published"
    board.ports.write_text("[]")  # its server stopped
    board.wait_for_selector("a.chip:has-text(':3000')", state="detached")
    board.ports.write_text(json.dumps([{"run_id": RUN, "ref": ":3000", "title": "t", "url": f"http://{{host}}:{port}/published"}]))
    board.wait_for_selector("a.chip:has-text(':3000')")
    board.click("button[aria-label='Delete session']")
    closes(published, board)  # deleting the session closes its port's tab too


def test_deleting_a_session_closes_its_tabs_and_only_its_own(board):
    board.resume()
    session = opens_tab(board, lambda: board.click("button.session"))
    code = opens_tab(board, lambda: board.click("button[aria-label='VS Code']"))
    assert "/vscode/?folder=" in code.url
    its_pr = opens_tab(board, lambda: board.click("a.chip:has-text('#3')"))
    issue = opens_tab(board, lambda: board.click("text=A bug"))
    term = opens_tab(board, lambda: board.click("button[aria-label='Terminal']"))

    board.click("button[aria-label='Delete session']")
    for tab in (session, code, its_pr):
        closes(tab, board)
    assert not issue.is_closed() and not term.is_closed() and not board.is_closed()


def test_deleting_a_session_asks_before_closing_its_open_pull_request(board):
    board.resume()
    board.wait_for_selector("a.chip.fail")
    board.answers.append(False)  # no: the pull request stays open
    board.click("button[aria-label='Delete session']")
    board.wait_for_selector("text=Nobody at work.")
    assert board.asked == ["Close #3 too?"]  # only the open one of this run: not the merged one, nor #4
    board.wait_for_timeout(500)
    assert not board.actions.exists()

    board.resume()
    board.wait_for_selector("a.chip.fail")
    board.click("button[aria-label='Delete session']")  # yes, this time
    board.wait_for_selector("text=Nobody at work.")
    for _ in range(50):
        if board.actions.exists():
            break
        board.wait_for_timeout(100)
    assert board.actions.read_text() == "github-auth close-pr 3\n"


def test_stopping_keeps_the_session_and_its_tab_and_deleting_closes_them(board):
    board.resume()
    session = opens_tab(board, lambda: board.click("button.session"))
    session.on("dialog", lambda d: d.accept())
    its_pr = opens_tab(board, lambda: board.click("a.chip:has-text('#3')"))
    session.click("button[aria-label='Stop session']")
    session.wait_for_selector("text=exited")  # still open, to read how it ended
    board.wait_for_selector("button.session.ended")  # listed still, to resume, and no longer stoppable
    board.wait_for_selector("button[aria-label='Stop session']", state="detached")
    assert not its_pr.is_closed()
    session.click("button[aria-label='Delete session']")  # its own page asks about #3 too
    closes(session, board)
    closes(its_pr, board)  # the dashboard heard it on the `sandbox-tabs` channel
    board.wait_for_selector("text=Nobody at work.")


def test_ctrl_c_copies_a_selection_and_interrupts_without_one(board):
    board.context.grant_permissions(["clipboard-read", "clipboard-write"])
    term = opens_tab(board, lambda: board.click("button[aria-label='Terminal']"))
    term.click(".xterm")
    term.keyboard.type("echo copy-me-$((40+2))\n")
    term.wait_for_selector("text=copy-me-42")
    term.evaluate("term.selectAll()")
    term.keyboard.press("Control+c")
    assert "copy-me-42" in term.evaluate("navigator.clipboard.readText()")
    term.evaluate("navigator.clipboard.writeText('')")
    term.keyboard.press("Control+Shift+c")  # nothing selected any more: copies nothing
    term.keyboard.type("sleep 30\n")
    term.wait_for_timeout(1000)  # the sleep is running, not the shell reading its line
    term.keyboard.press("Control+c")  # nothing selected: an interrupt, as ever
    term.keyboard.type("echo back-$((1+1))\n")
    term.wait_for_selector("text=back-2", timeout=5000)  # the sleep was interrupted
    assert term.evaluate("navigator.clipboard.readText()") == ""


def test_shift_drag_selects_while_the_program_has_the_mouse(board):
    term = opens_tab(board, lambda: board.click("button[aria-label='Terminal']"))
    term.click(".xterm")
    term.keyboard.type("printf '\\033[?1000h'; echo mouse-taken\n")  # what a TUI does
    term.wait_for_selector("text=mouse-taken")
    box = term.locator(".xterm-screen").bounding_box()
    drag = lambda: (term.mouse.move(box["x"] + 5, box["y"] + 5), term.mouse.down(),  # noqa: E731
                    term.mouse.move(box["x"] + 200, box["y"] + 40), term.mouse.up())
    drag()
    assert not term.evaluate("term.hasSelection()")  # the drag went to the program
    term.keyboard.down("Shift")
    drag()
    term.keyboard.up("Shift")
    assert term.evaluate("term.hasSelection()")


def test_resolve_starts_a_session_on_the_items_task(board):
    session = opens_tab(board, lambda: board.click("button:has-text('Resolve')"))
    session.wait_for_selector("text=on: Fix issue #7 now")  # run.sh --run-id <id> --task <task>
    [s] = json.load(urllib.request.urlopen(board.base + "/api/state"))["sessions"]
    assert s["kind"] == "run" and session.url.endswith("#" + s["id"])
    board.wait_for_selector("button.session")


@pytest.mark.parametrize("keys", ["Control+v", "Control+Shift+v"])
def test_ctrl_v_pastes(board, keys):
    board.context.grant_permissions(["clipboard-read", "clipboard-write"])
    term = opens_tab(board, lambda: board.click("button[aria-label='Terminal']"))
    term.click(".xterm")
    term.evaluate("navigator.clipboard.writeText('pasted-$((2+3))')")
    term.keyboard.type("echo ")
    term.keyboard.press(keys)
    term.keyboard.type("\n")
    term.wait_for_selector("text=pasted-5", timeout=5000)


def test_the_gear_configures_the_projects_plugins_in_its_claude_sandbox_json(board):
    file = board.project / ".claude-sandbox.json"
    file.write_text(json.dumps({"plugins": {"git-workspace": {"branchPrefix": "bot"}, "retired": {"x": 1}}}))
    board.click("button[aria-label='Settings']")
    board.wait_for_selector("dialog[open] b:has-text('docker-cli')")
    assert board.input_value("textarea[name='settings-git-workspace']").replace(" ", "").replace("\n", "") \
        == '{"branchPrefix":"bot"}'
    assert "briefing" in board.get_attribute("textarea[name='settings-kvm']", "placeholder")  # the example's
    board.select_option("select[name='enabled-docker-cli']", "off")
    board.select_option("select[name='enabled-kvm']", "on")
    board.click("dialog details:has(textarea[name='settings-kvm']) summary")
    board.fill("textarea[name='settings-kvm']", "not json")
    board.click("dialog button[type=submit]")
    board.wait_for_selector("dialog .error:has-text('kvm: not a JSON object')")
    assert json.loads(file.read_text())["plugins"]["git-workspace"] == {"branchPrefix": "bot"}  # unsaved

    board.fill("textarea[name='settings-kvm']", '{"briefing": "VMs in /data"}')
    board.fill("textarea[name='env']", '{"CLAUDE_EFFORT": "high"}')
    board.click("dialog button[type=submit]")
    board.wait_for_selector("dialog[open]", state="detached")
    assert json.loads(file.read_text()) == {
        "plugins": {"git-workspace": {"branchPrefix": "bot"}, "retired": {"x": 1},
                    "docker-cli": {"enabled": False}, "kvm": {"briefing": "VMs in /data", "enabled": True}},
        "env": {"CLAUDE_EFFORT": "high"}}

    board.click("button[aria-label='Settings']")  # opens on what the file holds now
    board.wait_for_selector("dialog[open]")
    assert board.input_value("select[name='enabled-docker-cli']") == "off"
    board.select_option("select[name='enabled-docker-cli']", "")  # back to its default: no entry
    board.click("dialog button[type=submit]")
    board.wait_for_selector("dialog[open]", state="detached")
    assert "docker-cli" not in json.loads(file.read_text())["plugins"]
