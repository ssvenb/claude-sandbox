"""web/index.html and web/session.html in a real browser: tabs, closing, favicons, CI marks.

The server and its pages run from a copy of web/, next to a stub run.sh: `--web` answers with the
JSON below (what the plugins would describe, tested on their own in test_plugin_hosts.py), and a
session is an "agent" that waits for a line, then exits 4. `docker` does nothing (stopping a session
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
  *) echo "agent $2 at work${4:+ on: $4}"; read line; exit 4 ;;
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
    (sandbox / "web.json").write_text(json.dumps({"notes": [], "checkout": f"{tmp_path}/mirrors/*-{{run_id}}", "lists": [
        {"title": "Pull requests", "items": [
            {"ref": "#3", "title": "Agent's work", "url": f"{elsewhere}/pr/3", "run_id": RUN,
             "status": "fail", "status_text": "CI: 1 of 2 checks failed"},
            {"ref": "#4", "title": "By hand", "url": f"{elsewhere}/pr/4", "status": "ok", "status_text": "CI: 2 checks passed"}]},
        {"title": "Issues", "items": [{"ref": "#7", "title": "A bug", "url": f"{elsewhere}/issues/7",
                                       "start": {"label": "Resolve", "task": "Fix issue #7 now"}}]}]}))

    context = browser.new_context()
    page = context.new_page()
    page.on("dialog", lambda d: d.accept())  # the "Stop …?" confirmations
    page.goto(base)
    page.wait_for_selector("a .num")

    def resume():
        """A session of RUN, the way the PR's Resume button starts one."""
        req = urllib.request.Request(base + "/api/sessions", json.dumps(
            {"project": str(project), "kind": "resume", "run_id": RUN}).encode())
        s = json.load(urllib.request.urlopen(req))
        page.wait_for_selector("button.session")
        return s
    page.resume = resume
    page.base, page.checkout = base, checkout
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
    for name in ("New session", "Terminal"):  # icon buttons: a glyph, named for screen readers
        button = board.query_selector(f"button[aria-label='{name}']")
        assert button.inner_text() == "" and button.query_selector("svg") and button.get_attribute("title")
    board.resume()
    board.wait_for_function("document.querySelector('.totals').innerText.includes('1\\nSessions')")
    totals = board.inner_text(".totals").split()
    assert totals == ["1", "Sessions", "2", "Pull", "requests", "1", "Issues"]
    failing, passing = board.query_selector_all("a .status")
    assert (failing.get_attribute("class"), failing.inner_text()) == ("status fail", "✕")
    assert (passing.get_attribute("class"), passing.inner_text()) == ("status ok", "✓")
    assert "CI: 1 of 2 checks failed" in board.get_attribute("a:has(.status.fail)", "title")


def test_a_session_has_one_tab_with_a_lamp_lit_while_it_runs(board):
    board.resume()
    tab = opens_tab(board, lambda: board.click("button.session"))
    tab.wait_for_selector("text=running")
    assert "#f2b84b" in icon(tab) and "<circle" in icon(tab)
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


def test_one_tab_per_pull_request(board):
    pr = opens_tab(board, lambda: board.click("text=By hand"))
    assert pr.url.endswith("/pr/4")
    again_opens_nothing(board, lambda: board.click("text=By hand"))  # GitHub's tab: another origin
    issue = opens_tab(board, lambda: board.click("text=A bug"))
    assert issue.url.endswith("/issues/7")


def test_deleting_a_session_closes_its_tabs_and_only_its_own(board):
    board.resume()
    session = opens_tab(board, lambda: board.click("button.session"))
    code = opens_tab(board, lambda: board.click("button[aria-label='VS Code']"))
    assert "/vscode/?folder=" in code.url
    its_pr = opens_tab(board, lambda: board.click("text=Agent's work"))
    other_pr = opens_tab(board, lambda: board.click("text=By hand"))
    term = opens_tab(board, lambda: board.click("button[aria-label='Terminal']"))

    board.on("dialog", lambda d: d.accept())
    board.click("button[aria-label='Delete session']")
    for tab in (session, code, its_pr):
        closes(tab, board)
    assert not other_pr.is_closed() and not term.is_closed() and not board.is_closed()


def test_stopping_keeps_the_session_and_its_tab_and_deleting_closes_them(board):
    board.resume()
    session = opens_tab(board, lambda: board.click("button.session"))
    session.on("dialog", lambda d: d.accept())
    its_pr = opens_tab(board, lambda: board.click("text=Agent's work"))
    session.click("button[aria-label='Stop session']")
    session.wait_for_selector("text=exited")  # still open, to read how it ended
    board.wait_for_selector("button.session.ended")  # listed still, to resume, and no longer stoppable
    board.wait_for_selector("button[aria-label='Stop session']", state="detached")
    assert not its_pr.is_closed()
    session.click("button[aria-label='Delete session']")
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
