"""The web UI (web: the dashboard, a session's chat, an agent's terminal) in a real browser: the
dashboard, a session's chat from its first moment, tabs, closing, favicons, CI marks, day and night.

The server runs from a copy of src/server with the built pages (web/dist, built first when
it is missing or older than its sources: see test_web.build_ui), next to a stand-in run.sh
(tests/stubs/chat_run.py):
`--web` answers with the JSON below (what the plugins would describe, tested on their own in
test_plugin_hosts.py), `--web-action` is logged to `actions`, and a session is a sandbox that boots
and then an agent behind a chat bridge, whose turn depends on what it is asked ("ask", "long", …).
`docker` does nothing (stopping a session removes its container), `code` is the stand-in from
test_web.py. Skipped without Playwright (pip install playwright, then
`python -m playwright install chromium`, or a chromium on the PATH).
"""
import base64
import json
import os
import shutil
import subprocess
import time
import urllib.request

import pytest

from conftest import REPO
from test_web import FAKE_DOCKER, STUB, ui_dist  # noqa: F401 (a fixture)

sync_api = pytest.importorskip("playwright.sync_api")

RUN = "abc123"  # the run the fixture's first pull request and checkout belong to

# `docker exec … python3 - ARG…` (git-workspace's changes, run in the run's container) runs here, in
# the checkout the server runs it in, without the server's environment as in a container.
# `docker run` is VS Code's container (FAKE_DOCKER); every other docker call does nothing.
DOCKER = '#!/bin/sh\n[ "$1" = run ] && exec fake-docker "$@"\n[ "$1" = exec ] || exit 0\nwhile [ "$1" != python3 ]; do shift; done\nexec env -u WEB_RUN_ID "$@"\n'


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
def board(tmp_path, browser, ui_dist):
    sandbox = tmp_path / "sandbox"
    (sandbox / "web").mkdir(parents=True)  # the server and the built pages: not the app's sources or node_modules
    shutil.copytree(REPO / "src/server", sandbox / "src/server", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ui_dist, sandbox / "web/dist")
    shutil.copytree(REPO / "plugins", sandbox / "plugins")
    shutil.copytree(REPO / "agents", sandbox / "agents")
    # The server reads the settings' authentications with the orchestrator's auth.py.
    shutil.copytree(REPO / "src/orchestrator", sandbox / "src/orchestrator", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(REPO / ".claude-sandbox.example.json", sandbox)
    tool(sandbox / "run.sh", STUB.read_text())
    tool(tmp_path / "bin/docker", DOCKER)
    tool(tmp_path / "bin/fake-docker", FAKE_DOCKER)
    project = tmp_path / "proj"
    project.mkdir()
    checkout = tmp_path / f"mirrors/proj-20261112-{RUN}"
    checkout.mkdir(parents=True)
    (tmp_path / "projects").mkdir()
    (tmp_path / "projects/proj.json").write_text(json.dumps({"repo": str(project)}))
    proc = subprocess.Popen([sandbox / "src/server/server.py", "--port", "0", "--projects", tmp_path / "projects"],
                            stdout=subprocess.PIPE, text=True,
                            env={"PATH": f"{tmp_path}/bin:/usr/bin:/bin", "HOME": str(tmp_path),
                                 "SHELL": "/bin/sh", "XDG_DATA_HOME": str(tmp_path / "data"), "STUB_BOOT": "0.02"})
    base = proc.stdout.readline().split()[1]
    # Items on another origin, as GitHub's are: localhost is the same server, another origin.
    elsewhere = base.replace("127.0.0.1", "localhost")
    (sandbox / "web.json").write_text(json.dumps({"notes": [], "agent": "claude", "checkout": f"{tmp_path}/mirrors/*-{{run_id}}",
        "plugins": ["agent-workspace", "git-workspace", "github-auth"],
        "commands": {"git-workspace": {"changes": [str(sandbox / "plugins/git-workspace/host/changes.py")]}},
        "servers": {"agent-workspace": [str(sandbox / "plugins/agent-workspace/host/vscode.py"), str(tmp_path / "mirrors")]},
        "live": [str(tmp_path / "ports.json")],
        "session_items": [{"run_id": RUN, "ref": "preview", "title": "The run's preview", "url": f"{elsewhere}/preview"}],
        "run_items": [
            {"ref": "#3", "title": "Agent's work", "url": f"{elsewhere}/pr/3", "run_id": RUN, "section": "Pull requests",
             "status": "fail", "status_text": "CI: 1 of 2 checks failed",
             "on_delete": {"plugin": "github-auth", "action": "close-pr", "arg": "3", "ask": "Close #3 too?"}},
            {"ref": "#2", "title": "Went in", "url": f"{elsewhere}/pr/2", "run_id": RUN,
             "note": "Merged", "status": "done", "status_text": "Merged"},
            {"ref": "#4", "title": "By hand", "url": f"{elsewhere}/pr/4", "section": "Pull requests", "status": "ok", "status_text": "CI: 2 checks passed",
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
    page.evaluate("document.fonts.ready")  # the web fonts are in: nothing changes its width under a test that measures
    page.actions = sandbox / "actions"
    page.web_json = sandbox / "web.json"

    def resume():
        """A session of RUN, the way the PR's Resume button starts one."""
        req = urllib.request.Request(base + "/api/sessions", json.dumps(
            {"project": "proj", "kind": "resume", "run_id": RUN}).encode())
        s = json.load(urllib.request.urlopen(req))
        page.wait_for_selector(".window")
        return s
    page.resume = resume
    page.base, page.checkout, page.ports = base, checkout, tmp_path / "ports.json"
    page.project, page.hold, page.commands = project, sandbox / "hold", sandbox / "commands"
    yield page
    context.close()
    for s in json.load(urllib.request.urlopen(base + "/api/state"))["sessions"]:  # they would outlive the server
        urllib.request.urlopen(urllib.request.Request(f"{base}/api/sessions/{s['id']}/delete", b""))
    for _ in range(100):  # each one's folder goes once it has ended
        if not any(tmp_path.glob(".local/state/claude-sandbox/sessions/*")):
            break
        time.sleep(0.05)
    proc.terminate()
    proc.wait(10)


def terminal(board):
    """The terminal tab of a session with its agent's own TUI (the stub's is a shell)."""
    s = json.load(urllib.request.urlopen(urllib.request.Request(board.base + "/api/sessions", json.dumps(
        {"project": "proj", "kind": "run", "ui": "terminal"}).encode())))
    return opens_tab(board, lambda: board.evaluate(f"window.open('/session#{s['id']}')"))


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


def delete(board):
    """Deletes the one session, as the dashboard lets you: stop its window, then delete it where its project lists the ended ones."""
    board.click(".window button[aria-label='Stop session']")
    board.click("ul.ended button[aria-label='Delete session']")


def icon(tab):
    return tab.eval_on_selector("link[rel=icon]", "e => decodeURIComponent(e.href)")


ROW = ".window"  # a running session, under its project on the left
NOBODY = ".board:not(:has(.running)):not(:has(ul.ended))"  # no session left, running or ended


def state(board):
    return json.load(urllib.request.urlopen(board.base + "/api/state"))["sessions"]


def test_the_dashboard_is_a_chat_bar_over_running_sessions_and_projects(board):
    assert board.title() == "Dashboard" and "<rect" in icon(board)
    assert board.query_selector("h1") is None and board.query_selector(".totals") is None
    assert board.locator("h2.band").all_inner_texts() == ["Projects"]  # nothing runs: no side for it, and no word about it
    assert "Nothing running" not in board.inner_text("#board")
    for name in ("New session", "Settings"):  # the project's buttons, on its panel on the right
        button = board.query_selector(f".project button[aria-label='{name}']")
        assert button.inner_text() == "" and button.query_selector("svg") and button.get_attribute("title")
    assert board.inner_text(".project .head h3 small") == "claude"  # the project's agent, as run.sh --web says
    assert " ".join(board.inner_text(".project h4").split()) == "Issues 1"  # what its plugins list, under it
    assert board.query_selector(".project button.session") is None  # and no sessions there
    board.resume()
    assert board.locator("h2.band").all_inner_texts() == ["Running now", "Projects"]
    assert board.inner_text(".running .group > h3") == "proj"  # a running session, under its project
    assert board.query_selector("button[aria-label='VS Code']") is None  # that is the session's own page's
    board.wait_for_selector(f"{ROW} a.chip .status")
    failing, merged = board.query_selector_all(f"{ROW} a .status")
    assert (failing.get_attribute("class"), failing.inner_text()) == ("status fail", "✕")
    assert (merged.get_attribute("class"), merged.inner_text()) == ("status done", "⇥")
    assert "CI: 1 of 2 checks failed" in board.get_attribute(f"{ROW} a:has(.status.fail)", "title")
    assert "Merged: Went in" in board.get_attribute(f"{ROW} a:has(.status.done)", "title")
    # The left is beside the right, both under the chat bar.
    bar, left, right = (board.locator(sel).bounding_box() for sel in (".starter", ".running", ".projects"))
    assert bar["y"] + bar["height"] <= left["y"] and left["x"] + left["width"] <= right["x"]


def test_with_nothing_running_each_project_sits_right_under_the_one_before(board):
    board.set_viewport_size({"width": 1280, "height": 800})
    board.evaluate("""() => {
        const {state, plugins} = dashboard, p = state.projects[0];
        plugins[p].lists[0].items = Array.from({length: 12}, (_, i) => ({ref: '#' + i, title: 'Issue ' + i, url: location.origin + '/i/' + i}));
        state.projects = [p, ...['/b', '/c', '/d'].map(q => p + q)];
        dashboard.render();
    }""")
    boxes = [board.locator(".project").nth(k).bounding_box() for k in range(4)]
    stacked = [(a, b) for a, b in zip(boxes, boxes[1:]) if a["x"] == b["x"]]
    assert stacked and all(abs(b["y"] - (a["y"] + a["height"]) - 12) < 1 for a, b in stacked)  # no row's gap under a short one


def test_each_side_of_the_dashboard_scrolls_on_its_own_under_a_chat_bar_that_stays(board):
    board.set_viewport_size({"width": 1280, "height": 500})
    board.resume()
    # More on each side than fits: sessions on the left, a long list on the right.
    board.evaluate("""() => {
        const {state, plugins} = dashboard, s = state.sessions[0];
        state.sessions = Array.from({length: 30}, (_, i) => ({...s, id: 'x' + i, run_id: null}));
        const said = plugins[state.projects[0]];
        said.lists[0].items = Array.from({length: 40}, (_, i) => ({ref: '#' + i, title: 'Issue ' + i, url: location.origin + '/i/' + i}));
        dashboard.render();
    }""")
    box = lambda sel: board.locator(sel).bounding_box()
    bar = box(".starter")
    for side, other in ((".running", ".projects"), (".projects", ".running")):
        assert board.eval_on_selector(side, "e => e.scrollHeight > e.clientHeight + 200")
        board.eval_on_selector(side, "e => e.scrollTo(0, 300)")
        assert board.eval_on_selector(side, "e => e.scrollTop") == 300
        assert board.eval_on_selector(other, "e => e.scrollTop") == 0  # the other side stays where it was
        board.eval_on_selector(side, "e => e.scrollTo(0, 0)")
    board.eval_on_selector(".running", "e => e.scrollTo(0, e.scrollHeight)")
    board.mouse.move(400, 300)
    board.mouse.wheel(0, 2000)  # the page itself has nowhere to go
    assert board.evaluate("[scrollY, document.documentElement.scrollHeight - innerHeight]") == [0, 0]
    assert box(".starter") == bar
    for side in (".running", ".projects"):  # both end at the window's bottom edge
        assert abs(box(side)["y"] + box(side)["height"] - 500) < 1

    board.set_viewport_size({"width": 600, "height": 500})  # one column: the page scrolls, the bar stays at its top
    board.mouse.wheel(0, 900)
    board.wait_for_function("scrollY > 300")
    assert box(".starter")["y"] < 20


def test_a_list_with_nothing_on_it_is_not_shown(board):
    board.wait_for_selector(".project h4:has-text('Pull requests')")
    assert [" ".join(h.inner_text().split()) for h in board.query_selector_all(".project h4")] == ["Issues 1", "Pull requests 1"]
    # The last issue was closed, and the run's pull request merged.
    board.evaluate("() => { const said = dashboard.plugins[dashboard.state.projects[0]]; said.lists[0].items = [];"
                   " said.run_items = said.run_items.filter(i => i.ref !== '#3'); dashboard.render(); }")
    assert board.query_selector(".project h4") is None and "None" not in board.inner_text(".project")
    assert board.inner_text(".project .head h3").startswith("proj")  # the project stays, with its buttons


PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="  # one pixel
PASTE = """(el, data) => {
    const bytes = Uint8Array.from(atob(data), c => c.charCodeAt(0)), files = new DataTransfer();
    files.items.add(new File([bytes], 'shot.png', {type: 'image/png'}));
    el.dispatchEvent(new ClipboardEvent('paste', {clipboardData: files, bubbles: true, cancelable: true}));
}"""


def test_images_are_pasted_into_either_chat_bar_and_sent_with_the_message(board):
    board.focus(".starter textarea")
    board.eval_on_selector(".starter textarea", PASTE, PNG)
    board.eval_on_selector(".starter textarea", PASTE, PNG)
    board.wait_for_selector(".starter .shot >> nth=1")
    board.click(".starter .shot button[aria-label='Remove image']")  # one too many
    assert board.locator(".starter .shot img").count() == 1
    board.fill(".starter textarea", "what is this?")
    tab = opens_tab(board, lambda: board.click(".starter button[type=submit]"))
    assert board.locator(".starter .shot").count() == 0  # sent: the tray is empty again
    tab.wait_for_selector(".you:has-text('what is this?') .shots img")
    assert tab.get_attribute(".you img", "src") == "data:image/png;base64," + PNG
    tab.wait_for_selector(".say:has-text('Done with “what is this?”.')")

    tab.eval_on_selector("#input", PASTE, PNG)  # and one alone, in the session's own bar
    tab.wait_for_selector("#shots .shot img")
    tab.keyboard.press("Enter")
    tab.wait_for_selector(".you >> nth=1")
    assert tab.locator("#shots .shot").count() == 0 and tab.locator(".you >> nth=1").locator("img").count() == 1
    tab.wait_for_function("document.querySelectorAll('.turn').length === 2")
    picture = {"type": "image/png", "data": PNG}
    assert [json.loads(line) for line in board.commands.read_text().splitlines()] == [
        {"type": "prompt", "text": "what is this?", "images": [picture]}, {"type": "prompt", "text": "", "images": [picture]}]
    tab.reload()  # a page opened later shows them too
    tab.wait_for_selector(".you >> nth=1")
    assert tab.locator(".you img").count() == 2


def test_files_are_attached_in_the_chat_bar_and_sent_with_the_message(board):
    tab = opens_tab(board, lambda: board.click("button[aria-label='New session']"))
    tab.wait_for_selector("#input")
    with tab.expect_file_chooser() as chooser:
        tab.click("#attach")
    chooser.value.set_files([{"name": "notes.txt", "mimeType": "text/plain", "buffer": b"hi"},
                             {"name": "shot.png", "mimeType": "image/png", "buffer": base64.b64decode(PNG)}])
    tab.wait_for_selector("#shots .shot .file:text-is('notes.txt')")
    tab.wait_for_selector("#shots .shot img")
    tab.fill("#input", "read these")
    tab.keyboard.press("Enter")
    tab.wait_for_selector(".you:has-text('read these') .file:text-is('notes.txt')")
    assert tab.locator("#shots .shot").count() == 0 and tab.locator(".you img").count() == 1
    tab.wait_for_function("document.querySelectorAll('.turn').length === 1")
    assert json.loads(board.commands.read_text().splitlines()[-1]) == {
        "type": "prompt", "text": "read these", "images": [{"type": "image/png", "data": PNG}],
        "files": [{"name": "notes.txt", "data": "aGk="}]}


def test_what_runs_in_the_background_has_a_panel_of_its_own_where_each_task_can_be_stopped(board):
    tab = opens_tab(board, lambda: board.click("button[aria-label='New session']"))
    tab.wait_for_selector(".boot.ok")
    assert tab.is_hidden("#tasks")  # nothing in the background: no panel
    tab.fill("#input", "run it in the background")
    tab.keyboard.press("Enter")
    tab.wait_for_selector("#tasks summary:has-text('2 running')")
    tab.wait_for_selector("header .state.idle")  # the turn is over; they run on, apart from the conversation
    assert " ".join(tab.inner_text("#tasks summary").split()) == "Background npm run dev · Check the callers 2 running"
    assert tab.locator("#log #tasks").count() == 0 and tab.locator("#dock #tasks").count() == 1
    tab.click("#tasks summary")
    assert [" ".join(t.split()) for t in tab.locator("#tasks li").all_inner_texts()] == [
        "shell npm run dev", "agent Check the callers Reading src/app.py"]
    tab.reload()  # a page opened later has them too
    tab.wait_for_selector("#tasks summary:has-text('2 running')")
    tab.click("#tasks summary")
    tab.click("#tasks li:has-text('npm run dev') button[aria-label='Stop task']")
    tab.wait_for_selector("#tasks summary:has-text('1 running')")
    assert tab.locator("#tasks li").count() == 1 and tab.is_visible("#tasks li")  # still unfolded
    tab.click("#tasks li button[aria-label='Stop task']")
    tab.wait_for_selector("#tasks", state="hidden")
    sent = [json.loads(line) for line in board.commands.read_text().splitlines()]
    assert sent[1:] == [{"type": "task", "id": "bg1a"}, {"type": "task", "id": "bg1b"}]


def test_the_first_message_is_a_card_with_its_project_and_start_button_under_the_text(board):
    card, field = (board.locator(sel).bounding_box() for sel in (".starter", ".starter textarea"))
    button = lambda: board.locator(".starter .bar button[type=submit]").bounding_box()  # noqa: E731
    assert board.inner_text(".starter .bar .project") == "proj"  # one project: named, nothing to pick
    before = button()
    assert before["y"] >= field["y"] + field["height"] and before["y"] + before["height"] <= card["y"] + card["height"]
    board.fill(".starter textarea", "one\ntwo\nthree\nfour")
    assert board.locator(".starter").bounding_box()["height"] > card["height"] + 40
    assert button()["y"] > before["y"] + 40  # it stays on the card's bottom line
    # The rest is in a sidebar on the left on a desk, with no menu button.
    menu = board.locator("#board-menu").bounding_box()
    assert board.is_visible("#board-menu .sync") and not board.is_visible("button[aria-label='Menu']")
    assert menu["x"] == 0 and menu["x"] + menu["width"] <= card["x"]
    # The colours are at the top right, not in the sidebar.
    theme = board.locator(".top .theme").bounding_box()
    assert not board.is_visible("#board-menu .theme") and theme["x"] > card["x"] + card["width"]
    # On a phone it is behind the menu button beside the card: closed until asked, and Esc closes it again.
    board.set_viewport_size({"width": 400, "height": 800})
    assert not board.is_visible("#board-menu")
    board.click("button[aria-label='Menu']")
    assert board.is_visible("#board-menu .theme") and board.is_visible("#board-menu .sync") and not board.is_visible(".top .theme")
    board.keyboard.press("Escape")
    assert not board.is_visible("#board-menu")


def test_a_running_session_is_a_window_with_its_stop_button_top_right(board):
    board.resume()
    # How it is doing is the colour along its top, and nothing else: no lamp, no word for it.
    assert board.query_selector(".window .lamp, .window .spin, .window .state") is None and "Idle" not in board.inner_text(".window")
    # A strip cut to the card's own rounded shape: a layer as large as the card, painted 4px deep.
    strip = board.eval_on_selector(".window.idle", "e => { const c = getComputedStyle(e, '::before'), r = e.getBoundingClientRect();"
                                   " return [c.backgroundImage, c.borderTopLeftRadius, Math.abs(parseFloat(c.width) - r.width) < 0.5]; }")
    assert strip[1:] == [board.eval_on_selector(".window", "e => getComputedStyle(e).borderTopLeftRadius"), True]
    assert "4px" in strip[0] and strip[0].startswith("linear-gradient(" +
        board.evaluate("(() => { const p = document.createElement('p'); p.style.color = 'var(--ok)'; document.body.append(p);"
                       " const c = getComputedStyle(p).color; p.remove(); return c; })()"))
    assert board.get_attribute(".window", "aria-label").endswith(": idle, waiting for its next task")  # said to a screen reader
    # Stop, then delete, in the window's top right corner.
    stop, delete, card = (board.locator(q).bounding_box() for q in
                          (".window button[aria-label='Stop session']", ".window button[aria-label='Delete session']", ".window"))
    assert stop["y"] - card["y"] < 20 and stop["x"] < delete["x"] and card["x"] + card["width"] - delete["x"] - delete["width"] < 20
    board.click(".window button[aria-label='Stop session']")
    board.wait_for_selector(".window", state="detached")  # stopped, not opened


def test_the_dashboard_shows_the_sessions_waiting_on_you_first(board):
    board.fill(".starter textarea", "please ask me")  # starting a session is writing its first message
    asking = opens_tab(board, lambda: board.click(".starter button[type=submit]"))
    asking.wait_for_selector(".ask")
    board.resume()  # a second one, idle after its boot
    board.wait_for_selector(".window.idle")
    board.wait_for_selector(".window.question")
    first, second = board.query_selector_all(".window")
    assert "question" in first.get_attribute("class") and first.query_selector(".open").inner_text() == "please ask me"
    assert "An earlier answer." in second.query_selector(".doing").inner_text()  # idle: what it last said
    assert [c.text_content() for c in second.query_selector_all("a.chip")] == ["✕#3", "⇥#2", "preview"]
    again_opens_nothing(board, lambda: board.click(".window.question .open"))  # its tab is open already
    assert board.input_value(".starter textarea") == ""

    asking.click(".ask .options button:has-text('Postgres')")
    board.wait_for_selector(".window.question", state="detached")
    assert board.locator(".window.idle").count() == 2


def test_a_session_has_one_tab_with_a_lamp_in_the_colour_of_what_its_agent_does(board):
    board.resume()
    board.wait_for_selector(".window.idle")  # booted and waiting: green
    tab = opens_tab(board, lambda: board.click(".window .open"))
    assert tab.url.endswith("/chat#" + state(board)[0]["id"])
    tab.wait_for_selector(".say:has-text('An earlier answer.')")  # a resumed run: its conversation so far
    assert tab.inner_text(".you") == "What was said before the resume"
    tab.wait_for_selector("header .state.idle")
    assert "#6fd3a2" in icon(tab) and "<circle" in icon(tab)
    again_opens_nothing(board, lambda: board.click(".window .open"))

    tab.fill("#input", "ask me something")
    tab.keyboard.press("Enter")
    tab.wait_for_selector(".ask")  # the stand-in asks: violet, here and on the dashboard
    tab.wait_for_function("decodeURIComponent(document.querySelector('link[rel=icon]').href).includes('#c69cff')")
    board.wait_for_selector(".window.question")
    assert tab.inner_text("header .state") == "Needs you"

    tab.on("dialog", lambda d: d.accept())
    tab.click("button[aria-label='Stop session']")
    tab.wait_for_selector("text=Session ended")
    tab.wait_for_function("decodeURIComponent(document.querySelector('link[rel=icon]').href).includes('stroke')")
    assert tab.is_disabled("#input")
    board.wait_for_selector("ul.ended button[aria-label='Resume session']")  # listed on its project's panel
    assert " ".join(board.inner_text(".project h4:has-text('Sessions')").split()) == "Sessions 1"  # under its own header
    assert board.query_selector("details") is None and board.query_selector("text=1 ended") is None  # with nothing to unfold
    with tab.expect_navigation():  # resuming takes this tab to the run's new session
        tab.click(".over button:has-text('Resume')")
    tab.wait_for_selector("header .state.idle")
    assert tab.url.endswith("#" + [s for s in state(board) if s["exit"] is None][0]["id"])
    assert len(state(board)) == 1  # the ended one is replaced: a run stays one session
    board.wait_for_selector("ul.ended", state="detached")


def test_the_first_message_is_written_while_the_sandbox_starts_and_sent_when_it_is_ready(board):
    board.hold.write_text("")  # the sandbox boots for as long as this is there
    tab = opens_tab(board, lambda: board.click("button[aria-label='New session']"))
    tab.wait_for_selector(".boot.starting .spin")  # whatever loads, turns
    tab.wait_for_selector(".boot .line:has-text('Cloning into /workspace')")
    assert tab.locator("#log > *").count() == 1 and tab.get_attribute("#input", "placeholder") == "Message"  # no explanations
    assert tab.inner_text("header .state") == "Starting" and "stroke-dasharray" in icon(tab)
    assert tab.evaluate("document.activeElement.id") == "input"  # ready to type from the first moment
    tab.fill("#input", "change main")
    tab.keyboard.press("Enter")
    tab.wait_for_selector(".you.queued:has-text('change main')")
    assert tab.inner_text(".you.queued") == "change main"
    tab.fill("#input", "and a second one")
    tab.keyboard.press("Enter")
    tab.wait_for_selector(".you.queued >> nth=1")
    board.wait_for_selector(".window.starting .doing:text-is('2 messages waiting')")
    assert board.query_selector(".window .spin") is None  # its colour says it starts
    assert board.inner_text(".window .open") == "change main"  # a session is called what it was first asked
    assert not board.commands.exists()  # nothing reached the agent yet

    board.hold.unlink()
    tab.wait_for_selector(".boot.ok:has-text('Sandbox ready')")
    tab.wait_for_selector(".you.queued", state="detached")
    tab.wait_for_selector(".say:has-text('Done with “and a second one”.')")
    sent = [json.loads(line)["text"] for line in board.commands.read_text().splitlines()]
    assert sent == ["change main", "and a second one"]  # in the order they were written
    assert tab.title() == "change main · proj"
    tab.click(".boot summary")  # the boot's output is kept, folded away
    assert "🔐 gh auth login" in tab.inner_text(".boot pre")


def test_a_chat_draws_what_the_agent_says_and_does(board):
    tab = opens_tab(board, lambda: board.click("button[aria-label='New session']"))
    tab.fill("#input", "change main")
    tab.keyboard.press("Enter")
    tab.wait_for_selector(".turn")
    # Its prose is markdown, built as elements: a heading, a list, a table, code with a Copy button.
    said = tab.locator(".say").last
    assert said.locator("h2").inner_text() == "What changed"
    assert said.locator("li >> nth=0").inner_text() == "main() now returns 2" and said.locator("li code").count() == 1
    assert said.locator("td >> nth=1").inner_text() == "one line"
    assert said.locator(".code pre").inner_text() == "def main():\n    return 2" and said.locator(".code .lang").inner_text() == "python"
    link = said.locator("a")
    assert (link.get_attribute("href"), link.get_attribute("target")) == ("https://example.com/docs", "_blank")
    assert tab.inner_text(".think") == "Thought" and tab.query_selector("details.think, .think summary") is None  # a line: nothing to open

    # What it did: a line per tool call, runs of them in one box; open one for what went in and came back.
    lines = [" ".join(t.inner_text().split()) for t in tab.query_selector_all("#log > .tools > .tool > summary")]
    assert lines == ["✓ Read /workspace/src/app.py", "✓ Edit /workspace/src/app.py", "✓ Subagent Check the callers",
                     "✓ Run python -m pytest -q"]
    tab.click(".tool:has-text('Edit') > summary")
    diff = tab.locator(".tool:has-text('Edit') .diff")
    assert [(r.get_attribute("class"), r.inner_text()) for r in diff.locator("span").element_handles()] == [
        ("same", "def main():"), ("del", "    return 1"), ("add", "    return 2")]
    tab.click(".tool:has-text('Subagent') > summary")  # a subagent's own calls, inside the call that started it
    assert "Search main\\( in src" in " ".join(tab.inner_text(".tool:has-text('Subagent') .kids .tool summary").split())
    tab.click(".tool:has-text('Run') > summary")
    assert tab.inner_text(".tool:has-text('Run') .body pre >> nth=1") == "3 passed in 0.12s"

    assert tab.inner_text(".turn") == "4 s · $0.10 · 3% context"
    assert " ".join(tab.inner_text("#plan summary").split()) == "Plan All done 3 of 3"
    assert tab.inner_text("header .who span") == f"proj / {state(board)[0]['run_id']} / claude, fable"

    assert tab.query_selector("#suggest") is None  # no next prompt is offered
    tab.fill("#input", "now fail")
    tab.keyboard.press("Enter")
    tab.wait_for_selector(".note.error:has-text('The API did not answer.')")
    assert tab.locator(".tool.failed pre.err").text_content().startswith("1 failing")  # folded, and marked

    tab.reload()  # a page opened later starts from the whole conversation
    tab.wait_for_selector(".note.error")
    assert tab.locator(".you").all_inner_texts() == ["change main", "now fail"]
    assert tab.locator("#log > .tools > .tool").count() == 6 and tab.locator(".turn").count() == 2


def test_a_chat_offers_the_agents_commands_and_models_and_can_interrupt_it(board):
    tab = opens_tab(board, lambda: board.click("button[aria-label='New session']"))
    tab.wait_for_selector("#model:not([hidden])")
    assert tab.locator("#model option").all_inner_texts() == ["Fable (Fable 5.2)", "Opus (Opus 5.5)"]
    tab.select_option("#model", "opus")
    tab.select_option("#effort", "high")
    tab.wait_for_function("document.title && document.querySelector('header .who span').innerText.endsWith('claude, opus')")

    tab.type("#input", "/")  # its commands and skills, as in the terminal
    assert tab.locator("#menu button b").all_inner_texts() == ["/compact", "/review", "/context"]
    tab.type("#input", "re")
    assert tab.locator("#menu button b").all_inner_texts() == ["/review"]
    tab.keyboard.press("Enter")  # picks it; a second Enter would send
    assert tab.input_value("#input") == "/review " and tab.is_hidden("#menu")
    tab.fill("#input", "")

    tab.fill("#input", "a long task\nover two lines")
    tab.keyboard.press("Enter")
    tab.wait_for_selector(".tool.running:has-text('sleep 600') .spin")  # the step it is on turns
    # and nothing else: not a line at the bottom, nor the thinking before it, though it only streamed
    assert tab.locator(".spin").count() == 1 and tab.query_selector("#tail") is None
    assert tab.inner_text(".think") == "Thought"
    assert tab.inner_text(".you") == "a long task\nover two lines"
    assert tab.is_visible("#halt")
    board.wait_for_selector(".window.working .doing.tool:has-text('Bash: Wait a long time')")
    tab.keyboard.press("Escape")  # as in the terminal
    tab.wait_for_selector(".tool.failed:has-text('sleep 600')")
    tab.wait_for_selector("#halt", state="hidden")
    tab.wait_for_selector(".spin", state="detached")  # nothing works: nothing turns
    sent = [json.loads(line) for line in board.commands.read_text().splitlines()]
    assert sent == [{"type": "model", "id": "opus"}, {"type": "effort", "level": "high"},
                    {"type": "prompt", "text": "a long task\nover two lines"}, {"type": "interrupt"}]


def test_a_question_is_answered_with_a_click_or_in_your_own_words(board):
    tab = opens_tab(board, lambda: board.click("button[aria-label='New session']"))
    tab.fill("#input", "ask me")
    tab.keyboard.press("Enter")
    tab.wait_for_selector(".ask .options button >> nth=1")
    assert tab.inner_text(".ask .q > b") == "Which database?" and tab.inner_text(".ask .q > small") == "Storage"
    tab.click(".ask .options button:has-text('SQLite')")
    tab.wait_for_selector(".say:has-text('Going with SQLite.')")
    assert " ".join(tab.inner_text(".ask.settled").split()) == "Which database? SQLite"

    tab.fill("#input", "ask again")
    tab.keyboard.press("Enter")
    tab.wait_for_selector(".ask:not(.settled) .other input")
    tab.fill(".ask:not(.settled) .other input", "DuckDB")
    tab.keyboard.press("Enter")
    tab.wait_for_selector(".say:has-text('Going with DuckDB.')")

    tab.fill("#input", "ask once more")
    tab.keyboard.press("Enter")
    tab.click(".ask:not(.settled) button:has-text('Dismiss')")
    tab.wait_for_selector(".say:has-text('Dismissed, so I chose myself.')")
    assert " ".join(tab.locator(".ask.settled").last.inner_text().split()) == "Which database? Dismissed"


def test_the_pages_follow_the_browsers_day_or_night_unless_one_is_pinned(board):
    paper = lambda page: page.evaluate("getComputedStyle(document.body).backgroundColor")  # noqa: E731
    board.emulate_media(color_scheme="light")
    day = paper(board)
    board.emulate_media(color_scheme="dark")
    night = paper(board)
    assert day == "rgb(233, 234, 244)" and night == "rgb(27, 29, 54)"
    board.click(".top .theme button[aria-label='Day']")  # pinned: the browser's setting no longer decides
    assert paper(board) == day and board.get_attribute(".top .theme button[aria-label='Day']", "aria-pressed") == "true"
    tab = opens_tab(board, lambda: board.click("button[aria-label='New session']"))
    tab.emulate_media(color_scheme="dark")
    assert tab.evaluate("document.documentElement.dataset.theme") == "light"  # the chat wears it too
    tab.click(".theme button[aria-label='Follow the browser']")
    assert tab.evaluate("document.documentElement.dataset.theme") is None
    assert paper(tab) == "rgb(15, 17, 35)"
    term = terminal(board)
    term.emulate_media(color_scheme="light")
    # and so does the terminal (which comes with xterm.js, loaded after the page itself)
    term.wait_for_function("window.term && term.options.theme.background === '#fbfbfe'")
    term.emulate_media(color_scheme="dark")
    term.wait_for_function("term.options.theme.background === '#0f1123'")


def test_one_tab_per_item(board):
    issue = opens_tab(board, lambda: board.click("text=A bug"))
    assert issue.url.endswith("/issues/7")
    again_opens_nothing(board, lambda: board.click("text=A bug"))  # GitHub's tab: another origin


def test_a_runs_pull_request_is_on_its_session_or_with_none_listed_on_its_projects_panel(board):
    # No session of the run yet: its open pull request is on the project's panel, to resume it.
    assert board.query_selector("a.chip") is None
    board.wait_for_selector(".project h4:has-text('Pull requests')")
    assert board.text_content(".project h4:has-text('Pull requests') .count") == "1"
    listed = board.query_selector(".project li:has-text(\"Agent's work\")")
    assert "CI: 1 of 2 checks failed" in listed.query_selector("a").get_attribute("title")
    assert board.query_selector("text=Went in") is None  # its merged one: on a session's row only
    assert board.query_selector("text=By hand") is None  # a pull request of no run: nowhere
    listed.query_selector("button:has-text('Resume')").click()
    board.wait_for_selector(f"{ROW} a.chip.fail")
    # Now on its session's window, and no longer a section of the panel.
    board.wait_for_selector(".project h4:has-text('Pull requests')", state="detached")
    row = board.query_selector(ROW)
    assert [c.text_content() for c in row.query_selector_all("a.chip")] == ["✕#3", "⇥#2", "preview"]
    assert "Agent's work" in board.get_attribute(f"{ROW} a.chip.fail", "title")
    assert "CI: 1 of 2 checks failed" in board.get_attribute(f"{ROW} a.chip.fail", "title")
    assert board.query_selector("a.chip.done")  # the run's merged one, too
    assert board.query_selector("text=By hand") is None  # a pull request of no run: nowhere
    pr = opens_tab(board, lambda: board.click(f"{ROW} a.chip.fail"))
    assert pr.url.endswith("/pr/3")
    again_opens_nothing(board, lambda: board.click(".window a.chip.fail"))  # the same tab, from its window
    preview = opens_tab(board, lambda: board.click(f"{ROW} a.chip:has-text('preview')"))
    assert preview.url.endswith("/preview")
    # Ended, the session is listed on its project's panel, its pull requests with it.
    board.click(".window button[aria-label='Stop session']")
    board.wait_for_selector("ul.ended a.chip.fail")
    assert [c.text_content() for c in board.query_selector_all("ul.ended a.chip")] == ["✕#3", "⇥#2", "preview"]
    assert board.query_selector(".project h4:has-text('Pull requests')") is None


def test_a_port_the_session_publishes_is_a_button_on_its_window_while_published(board):
    board.resume()
    port = board.base.rsplit(":", 1)[1]
    # As the central port proxy writes it: `{host}` is whatever name the page was opened by.
    board.ports.write_text(json.dumps([{"run_id": RUN, "ref": ":3000", "title": "Port 3000 of the sandbox",
                                        "url": f"http://{{host}}:{port}/published"}]))
    board.wait_for_selector(f"{ROW} a.chip:has-text(':3000')")
    assert board.get_attribute(f"{ROW} a.chip:has-text(':3000')", "href") == f"{board.base}/published"
    published = opens_tab(board, lambda: board.click(f"{ROW} a.chip:has-text(':3000')"))
    assert published.url == f"{board.base}/published"
    board.ports.write_text("[]")  # its server stopped
    board.wait_for_selector("a.chip:has-text(':3000')", state="detached")
    board.ports.write_text(json.dumps([{"run_id": RUN, "ref": ":3000", "title": "t", "url": f"http://{{host}}:{port}/published"}]))
    board.wait_for_selector(f"{ROW} a.chip:has-text(':3000')")
    delete(board)
    closes(published, board)  # deleting the session closes its port's tab too


def test_deleting_a_session_closes_its_tabs_and_only_its_own(board):
    board.resume()
    session = opens_tab(board, lambda: board.click(".window .open"))
    session.on("dialog", lambda d: d.accept())
    code = opens_tab(session, lambda: session.click("button[aria-label='VS Code']"))  # from the session's own page
    assert "/plugins/agent-workspace/?folder=" in code.url
    its_pr = opens_tab(board, lambda: board.click(f"{ROW} a.chip:has-text('#3')"))
    issue = opens_tab(board, lambda: board.click("text=A bug"))

    delete(board)
    for tab in (session, code, its_pr):
        closes(tab, board)
    assert not issue.is_closed() and not board.is_closed()


def test_deleting_a_session_asks_before_closing_its_open_pull_request(board):
    board.resume()
    board.wait_for_selector(f"{ROW} a.chip.fail")
    board.answers.append(False)  # no: the pull request stays open
    delete(board)
    board.wait_for_selector(NOBODY)
    assert board.asked == ["Close #3 too?"]  # only the open one of this run: not the merged one, nor #4
    board.wait_for_timeout(500)
    assert not board.actions.exists()

    board.resume()
    board.wait_for_selector(f"{ROW} a.chip.fail")
    delete(board)  # yes, this time
    board.wait_for_selector(NOBODY)
    for _ in range(50):
        if board.actions.exists():
            break
        board.wait_for_timeout(100)
    assert board.actions.read_text() == "github-auth close-pr 3\n"


def test_deleting_asks_about_a_pull_request_opened_since_the_page_last_looked(board):
    board.resume()
    board.wait_for_selector(f"{ROW} a.chip.fail")
    said = json.loads(board.web_json.read_text())
    said["run_items"].append({"ref": "#5", "title": "Just opened", "url": "u5", "run_id": RUN,
                              "on_delete": {"plugin": "github-auth", "action": "close-pr", "arg": "5", "ask": "Close #5 too?"}})
    board.web_json.write_text(json.dumps(said))
    delete(board)  # the page has not described the project again, the server does
    board.wait_for_selector(NOBODY)
    assert board.asked == ["Close #3 too?", "Close #5 too?"]


def test_stopping_keeps_the_session_and_its_tab_and_deleting_closes_them(board):
    board.resume()
    session = opens_tab(board, lambda: board.click(".window .open"))
    session.on("dialog", lambda d: d.accept())
    its_pr = opens_tab(board, lambda: board.click(f"{ROW} a.chip:has-text('#3')"))
    session.wait_for_selector(".chips a.chip.fail:has-text('#3')")  # its pull request, on its own page too
    session.click("button[aria-label='Stop session']")
    session.wait_for_selector("text=Session ended")  # still open, to read how it ended
    board.wait_for_selector(".window", state="detached")  # no window: nothing runs
    board.wait_for_selector("button[aria-label='Stop session']", state="detached")
    board.wait_for_selector("ul.ended button.session")  # listed still, on its project's panel, to resume or delete
    assert board.inner_text("ul.ended button.session") == "Session " + RUN
    assert [c.text_content() for c in board.query_selector_all("ul.ended a.chip")] == ["✕#3", "⇥#2", "preview"]
    assert board.is_visible("ul.ended button[aria-label='Resume session']")
    assert not its_pr.is_closed()
    session.click("button[aria-label='Delete session']")  # its own page asks about #3 too
    closes(session, board)
    closes(its_pr, board)  # the dashboard heard it on the `sandbox-tabs` channel
    board.wait_for_selector(NOBODY)


def test_ctrl_c_copies_a_selection_and_interrupts_without_one(board):
    board.context.grant_permissions(["clipboard-read", "clipboard-write"])
    term = terminal(board)
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
    term = terminal(board)
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
    session.wait_for_selector(".you:has-text('Fix issue #7 now')")  # the task is the session's first message
    session.wait_for_selector(".say:has-text('Done with “Fix issue #7 now”.')")
    [s] = state(board)
    assert (s["kind"], s["title"]) == ("run", "Fix issue #7 now") and session.url.endswith("/chat#" + s["id"])
    board.wait_for_selector(".window .open:has-text('Fix issue #7 now')")


@pytest.mark.parametrize("keys", ["Control+v", "Control+Shift+v"])
def test_ctrl_v_pastes(board, keys):
    board.context.grant_permissions(["clipboard-read", "clipboard-write"])
    term = terminal(board)
    term.click(".xterm")
    term.evaluate("navigator.clipboard.writeText('pasted-$((2+3))')")
    term.keyboard.type("echo ")
    term.keyboard.press(keys)
    term.keyboard.type("\n")
    term.wait_for_selector("text=pasted-5", timeout=5000)


def test_the_gear_configures_the_projects_plugins_in_its_file(board):
    """Every declared setting gets a control of its type; what the form has none for is kept. An
    authentication is picked from those configured of its type, by name."""
    auth = board.project.parent / ".config/claude-sandbox/auth.json"  # the server's HOME is the test's
    auth.parent.mkdir(parents=True)
    auth.write_text(json.dumps({"coder": {"type": "github-app"}, "reviewer": {"type": "github-app"},
                                "openai": {"type": "api-key", "key": "never-shown"}, "gcs": {"type": "gcp-service-account"}}))
    auth.chmod(0o600)
    file = board.project.parent / "projects/proj.json"
    file.write_text(json.dumps({"repo": str(board.project), "env": {"CLAUDE_EFFORT": "high", "GH_AUTH": "coder"},
                                "plugins": {"git-workspace": {"branchPrefix": "bot", "extra": 1}, "retired": {"x": 1}}}))
    board.click("button[aria-label='Settings']")
    board.wait_for_selector("dialog[open] b:has-text('docker-cli')")
    assert board.input_value("input[name='plugins.git-workspace.branchPrefix']") == "bot"
    assert board.input_value("input[name='repo']") == str(board.project)  # the repo it works on
    options = lambda sel: board.eval_on_selector_all(sel + " option", "os => os.map(o => o.value)")  # noqa: E731
    assert board.input_value("select[name='env.GH_AUTH']") == "coder"
    assert options("select[name='env.GH_AUTH']") == ["", "coder", "reviewer"]  # github-apps only
    assert "never-shown" not in board.content()  # names, never what they hold
    assert board.input_value("select[name='env.CLAUDE_EFFORT']") == "high"
    assert "extra" in board.text_content(".card:has(button[name='enabled-git-workspace']) .kept")
    assert not board.is_visible("input[name='repo']")  # each card folded to its head

    # Plugins: a switch each, its settings shown while it is on.
    assert board.get_attribute("button[name='enabled-docker-cli']", "aria-checked") == "true"  # the default
    board.click("button[name='enabled-docker-cli']")
    assert not board.is_visible("textarea[name='plugins.kvm.briefing']")  # kvm is off by default
    board.click("button[name='enabled-kvm']")
    for card in ("plugin-kvm", "agents", "agent-claude", "plugin-github-auth", "plugin-project-setup", "plugin-upstream-proxy"):
        board.click(f"[data-card='{card}'] > .head .toggle")  # a card shows only its head until clicked
    board.fill("textarea[name='plugins.kvm.briefing']", "VMs in /data")
    board.select_option("select[name='env.CLAUDE_EFFORT']", "max")
    board.select_option("select[name='env.GH_AUTH']", "")  # unset

    # Lists: + Add a row each; one left empty is not saved.
    deps = ".card:has(button[name='enabled-project-setup']) .field:has(label:text-is('apt packages'))"
    board.click(deps + " button.add")
    board.fill("input[name='plugins.project-setup.apt.0']", "ripgrep")
    board.click(deps + " button.add")

    # A route: an object in a list, its auth fields following the type picked.
    routes = ".card:has(button[name='enabled-upstream-proxy'])"
    board.click(routes + " .field:has(label:text-is('Routes')) > .control > .entries > button.add")
    board.fill("input[name='plugins.upstream-proxy.routes.0.name']", "api")
    board.fill("input[name='plugins.upstream-proxy.routes.0.upstream']", "https://api.example.com")
    board.check("input[name='plugins.upstream-proxy.routes.0.allowMethods.GET']")
    credential = "select[name='plugins.upstream-proxy.routes.0.auth.credential']"
    assert options(credential) == ["", "gcs", "openai"]  # what a route can authenticate with
    board.select_option(credential, "openai")
    board.fill("input[name='plugins.upstream-proxy.routes.0.auth.header']", "x-api-key")
    board.click(routes + " .field:has(> .label label:text-is('Container environment')) > .control button.add")
    board.fill("input[name='plugins.upstream-proxy.routes.0.containerEnv.0.key']", "API_URL")
    board.fill("input[name='plugins.upstream-proxy.routes.0.containerEnv.0.value']", "http://127.0.0.1:8081")
    board.click("dialog button[type=submit]")
    board.wait_for_selector("dialog .error:has-text('routes[0].port is required')")  # the server's check
    assert json.loads(file.read_text())["env"]["GH_AUTH"] == "coder"  # nothing saved
    board.fill("input[name='plugins.upstream-proxy.routes.0.port']", "8081")

    board.click("dialog button[type=submit]")
    board.wait_for_selector("dialog[open]", state="detached")
    assert json.loads(file.read_text()) == {
        "repo": str(board.project), "env": {"CLAUDE_EFFORT": "max"},
        "plugins": {"git-workspace": {"branchPrefix": "bot", "extra": 1}, "retired": {"x": 1},
                    "docker-cli": {"enabled": False}, "kvm": {"enabled": True, "briefing": "VMs in /data"},
                    "project-setup": {"apt": ["ripgrep"]},
                    "upstream-proxy": {"routes": [{"name": "api", "upstream": "https://api.example.com",
                                                   "allowMethods": ["GET"], "auth": {"credential": "openai", "header": "x-api-key"},
                                                   "containerEnv": {"API_URL": "http://127.0.0.1:8081"},
                                                   "port": 8081}]}}}

    board.click("button[aria-label='Settings']")  # opens on what the file holds now
    board.wait_for_selector("dialog[open]")
    assert board.get_attribute("button[name='enabled-docker-cli']", "aria-checked") == "false"
    board.click("button.reset-all")  # every plugin back to its defaults: no entries
    assert board.get_attribute("button[name='enabled-docker-cli']", "aria-checked") == "true"
    board.fill("input[type=search]", "branch prefix")  # the filter keeps the matching settings
    board.wait_for_selector("input[name='plugins.git-workspace.branchPrefix']", state="visible")  # its card unfolded
    assert not board.is_visible("button[name='enabled-kvm']")

    # The JSON view edits the whole file; a typo there is reported, not saved.
    board.click(".modes button:has-text('JSON')")
    text = board.input_value("textarea[name='json']")
    assert json.loads(text)["plugins"] == {"git-workspace": {"extra": 1}, "retired": {"x": 1}}  # what no form control holds stays
    edited = json.loads(text)
    edited["plugins"]["git-workspace"]["branchPrefix"] = "robot"
    text = json.dumps(edited)
    board.fill("textarea[name='json']", text)
    board.click(".modes button:has-text('Form')")
    assert board.input_value("input[name='plugins.git-workspace.branchPrefix']") == "robot"
    board.click(".modes button:has-text('JSON')")
    board.fill("textarea[name='json']", "{oops")
    board.click("dialog button[type=submit]")
    board.wait_for_selector("dialog .error:has-text('Not valid JSON')")
    board.fill("textarea[name='json']", text)
    board.click("dialog button[type=submit]")
    board.wait_for_selector("dialog[open]", state="detached")
    assert json.loads(file.read_text())["plugins"] == {"git-workspace": {"branchPrefix": "robot", "extra": 1}, "retired": {"x": 1}}


def test_the_menus_settings_add_and_delete_projects_and_edit_your_authentications(board):
    auth = board.project.parent / ".config/claude-sandbox/auth.json"
    auth.parent.mkdir(parents=True)
    auth.write_text(json.dumps({"coder": {"type": "github-app", "appId": "1", "privateKeyFile": "~/k.pem", "extra": 1}}))
    board.click("button[aria-label='Sandbox settings']")
    board.wait_for_selector("dialog[open] h2:has-text('Sandbox settings')")

    # Projects: added and deleted at once.
    board.fill("input[name='new-project.name']", "other")
    board.fill("input[name='new-project.repo']", "~/code/other")
    board.click("[data-card=projects] button.add")
    board.wait_for_selector("button[aria-label='Delete project other']")
    assert json.loads((board.project.parent / "projects/other.json").read_text()) == {"repo": "~/code/other"}
    board.once("dialog", lambda d: d.accept())
    board.click("button[aria-label='Delete project other']")
    board.wait_for_selector("button[aria-label='Delete project other']", state="detached")
    assert not (board.project.parent / "projects/other.json").exists()

    # Authentications: an entry each, its fields those of its type; what the form has none for is kept.
    assert board.input_value("input[name='auth.0.appId']") == "1"
    assert board.text_content("[data-card=auth] .kind h5") == "github-app"  # grouped by type
    board.click(".field:has(label:text-is('Entries')) > .control > .entries > button.add")
    board.fill("input[name='auth.1.name']", "openai")
    board.select_option("select[name='auth.1.type']", "api-key")
    assert not board.is_visible("input[name='auth.1.appId']")
    board.click("dialog button[type=submit]")
    board.wait_for_selector("dialog .error:has-text('lacks key')")  # the server's check
    board.fill("input[name='auth.1.key']", "sk")
    board.click("dialog button[type=submit]")
    board.wait_for_selector("dialog[open]", state="detached")
    assert json.loads(auth.read_text()) == {"coder": {"type": "github-app", "appId": "1", "privateKeyFile": "~/k.pem", "extra": 1},
                                            "openai": {"type": "api-key", "key": "sk"}}
    assert auth.stat().st_mode & 0o777 == 0o600

    # The JSON view edits the whole file.
    board.click("button[aria-label='Sandbox settings']")
    board.click(".modes button:has-text('JSON')")
    board.fill("textarea[name='json']", json.dumps({"openai": {"type": "api-key", "key": "sk2"}}))
    board.click("dialog button[type=submit]")
    board.wait_for_selector("dialog[open]", state="detached")
    assert json.loads(auth.read_text()) == {"openai": {"type": "api-key", "key": "sk2"}}


def test_the_files_a_runs_checkout_changed_are_beside_its_chat_or_behind_a_header_button(board):
    git = lambda *a: subprocess.run(["git", "-C", board.checkout, "-c", "user.name=t", "-c", "user.email=t@t", *a],  # noqa: E731
                                    check=True, capture_output=True)
    git("init", "-q", "-b", "main")
    (board.checkout / "app.py").write_text("a\nb\n")
    git("add", ".")
    git("commit", "-qm", "base")
    (board.checkout / "app.py").write_text("a\nc\nd\n")
    (board.checkout / "web/src").mkdir(parents=True)
    (board.checkout / "web/src/New.tsx").write_text("x\n")
    (board.checkout / "web/lib").mkdir(parents=True)
    (board.checkout / "web/lib/util.ts").write_text("1\n2\n")
    (board.checkout / "docs/guide").mkdir(parents=True)
    (board.checkout / "docs/guide/intro.md").write_text("hi\n")
    s = board.resume()
    tab = board.context.new_page()
    tab.set_viewport_size({"width": 1400, "height": 800})
    tab.goto(f"{board.base}/chat#{s['id']}")
    # On a desk: a column of its own left of the chat, the button not needed.
    tab.wait_for_selector("#changes .file:has-text('app.py')")
    # A tree of folders, each with the lines changed below it; a folder holding only a folder is one line with it.
    rows = lambda: [" ".join(t.split()) for t in tab.locator("#changes .file:visible, #changes summary:visible").all_inner_texts()]  # noqa: E731
    assert rows() == ["docs/guide +1", "web +3", "M app.py +2 −1"]  # folders start closed
    assert " ".join(tab.inner_text("#changes .head").split()) == "Changed files +6 −1"
    for name in ["docs/guide", "web", "lib", "src"]:  # a click opens one
        tab.click(f"#changes summary:has-text('{name}')")
    assert rows() == ["docs/guide +1", "A intro.md +1", "web +3", "lib +2", "A util.ts +2", "src +1", "A New.tsx +1", "M app.py +2 −1"]
    tab.click("#changes summary:has-text('web')")  # closed again: its folders and files go, its own line stays
    assert tab.is_hidden("#changes .file:has-text('util.ts')") and tab.is_visible("#changes summary:has-text('web')")
    assert tab.eval_on_selector("#changes", "e => e.getBoundingClientRect().right") < tab.eval_on_selector("#scroll", "e => e.getBoundingClientRect().left") + 1
    assert tab.is_hidden("header .files")
    # Narrower: a button in the header, its count on it, that opens the list over the chat.
    tab.set_viewport_size({"width": 400, "height": 800})
    assert tab.is_hidden("#changes")
    assert tab.inner_text("header .files") == "4"
    tab.click("header .files")
    tab.wait_for_selector("#changes .file:has-text('app.py')")
    tab.keyboard.press("Escape")
    tab.wait_for_selector("#changes", state="hidden")
    # The list follows the checkout.
    (board.checkout / "web/src/New.tsx").unlink()
    tab.wait_for_function("document.querySelector('header .files')?.innerText === '3'")


def test_the_menus_sign_in_to_claude_opens_its_page_and_takes_the_code_in_a_dialog(board, tmp_path):
    page = board.base + "/?claude-signin"  # where the stand-in claude sends you to sign in: a page that loads
    tool(tmp_path / "bin/claude", f"#!/bin/sh\necho 'visit: {page}'\nread c\n[ \"$c\" = good ] || {{ echo 'Bad code'; exit 1; }}\n")

    def sign_in():
        with board.context.expect_page() as tab:
            board.click("#board-menu button[aria-label='Sign in to Claude']")
        tab.value.wait_for_url(page)  # the server sent the tab on to the page claude printed
        tab.value.close()

    sign_in()
    code = board.get_by_role("textbox", name="Code")
    code.fill("bad")
    board.click("dialog button[type=submit]")
    board.wait_for_selector("dialog .error:text('Bad code')")
    # A failed code ends that sign-in: cancel, sign in anew, and the right code.
    board.click("dialog button:text('Cancel')")
    sign_in()
    assert board.inner_text("dialog .error") == ""
    code.fill("good")
    board.click("dialog button[type=submit]")
    board.wait_for_selector("dialog[aria-labelledby]", state="hidden")


def test_a_signed_out_claude_asks_to_sign_in_again_and_a_no_holds(board, tmp_path):
    page = board.base + "/?claude-signin"
    tool(tmp_path / "bin/claude", f"#!/bin/sh\n[ \"$2\" = status ] && exit 1\necho 'visit: {page}'\nread c\n")
    ask = board.locator("dialog:has-text('Signed out')")
    board.reload()
    ask.wait_for()
    with board.context.expect_page() as tab:
        ask.get_by_role("button", name="Sign in to Claude").click()
    tab.value.wait_for_url(page)
    tab.value.close()
    assert ask.is_hidden() and board.get_by_role("textbox", name="Code").is_visible()
    board.click("dialog button:text('Cancel')")
    board.reload()
    ask.get_by_role("button", name="Not now").click()
    board.reload()
    board.wait_for_timeout(1000)
    assert ask.is_hidden()  # asked no more until it is seen signed in again


def test_side_chats_are_asked_beside_the_chat_and_the_panels_are_dragged_and_put_away(board):
    subprocess.run(["git", "-C", board.checkout, "init", "-q", "-b", "main"], check=True)
    (board.checkout / "app.py").write_text("a\n")
    s = board.resume()
    tab = board.context.new_page()
    tab.set_viewport_size({"width": 1400, "height": 800})
    tab.goto(f"{board.base}/chat#{s['id']}")
    tab.wait_for_selector("#changes .file:has-text('app.py')")
    ends = lambda sel: tab.eval_on_selector(sel, "e => { const r = e.getBoundingClientRect(); return [r.left, r.right]; }")  # noqa: E731
    width = lambda sel: round(ends(sel)[1] - ends(sel)[0])  # noqa: E731
    # Three columns on a desk: the changed files, the chat, its side chats.
    tab.wait_for_selector("#sidechat .say:has-text('An earlier side answer.')")  # the one the resumed run kept
    assert ends("#changes")[1] <= ends("#scroll")[0] and ends("#scroll")[1] <= ends("#sidechat")[0]
    assert tab.inner_text("#sidechat .tab.on") == "What was asked beside it"
    # A question there is answered there: the conversation hears nothing of it.
    tab.fill("#sidechat textarea", "why main?")
    tab.keyboard.press("Enter")
    tab.wait_for_selector("#sidechat .say:has-text('About “why main?”')")
    assert "why main?" not in tab.inner_text("#log") and tab.inner_text("header .state") == "Idle"
    # Another one, a tab of its own, lit while it is answered; Esc in its field stops its turn only.
    tab.click("#sidechat button[aria-label='New side chat']")
    assert tab.inner_text("#sidechat .tab.on") == "New question" and tab.locator("#sidechat .log > *").count() == 0
    tab.keyboard.type("wait long")
    tab.keyboard.press("Enter")
    tab.wait_for_selector("#sidechat .tab.on:has-text('wait long') .lamp.working")
    tab.wait_for_selector("#sidechat .think:has-text('Thinking')")  # nothing said yet: it says it is at it
    tab.keyboard.press("Escape")
    tab.wait_for_selector("#sidechat .say:has-text('About “wait long”')")
    assert not tab.is_visible("#sidechat .think")
    assert {"type": "interrupt", "side": "2"} in [json.loads(line) for line in board.commands.read_text().splitlines()]
    tab.click("#sidechat [role=tab]:has-text('What was asked')")  # back to the first, with all that was said in it
    assert tab.locator("#sidechat .you").all_inner_texts() == ["What was asked beside it", "why main?"]
    tab.keyboard.press("ArrowRight")  # the arrows walk the tabs
    assert tab.inner_text("#sidechat .tab.on") == "wait long"
    tab.click("#sidechat .tab.on button[aria-label^='Close']")
    tab.wait_for_function("document.querySelectorAll('#sidechat .tab').length === 1")
    tab.reload()  # they are the session's, not the page's
    tab.wait_for_selector("#sidechat .say:has-text('About “why main?”')")
    assert tab.locator("#sidechat .tab").count() == 1
    tab.wait_for_selector("#changes .file")

    # A panel is as wide as its edge is dragged, or moved with the arrow keys; a double click undoes it.
    assert (width("#pane-right"), width("#pane-left")) == (380, 300)
    edge = tab.locator("#pane-right [role=separator]")
    x = ends("#pane-right")[0]
    tab.mouse.move(x, 400)
    tab.mouse.down()
    tab.mouse.move(x - 100, 400, steps=4)
    tab.mouse.up()
    assert width("#pane-right") == 480 and edge.get_attribute("aria-valuenow") == "480"
    edge.press("ArrowRight")
    assert width("#pane-right") == 464
    tab.locator("#pane-left [role=separator]").press("Home")
    assert width("#pane-left") == 200
    edge.dblclick()
    assert width("#pane-right") == 380
    # Put away from its own button in its top corner, the chat takes its room; the browser keeps both.
    # The header's button, there only while a panel is away, brings it back; the focus goes between the two.
    before = width("#scroll")
    assert tab.is_hidden("header .pane-toggle")
    tab.click("#pane-right button[aria-label='Hide side chats']")
    assert tab.is_hidden("#sidechat") and width("#scroll") == before + 380
    assert tab.evaluate("document.activeElement.getAttribute('aria-label')") == "Show side chats"
    tab.reload()
    tab.wait_for_selector("#changes .file")
    assert tab.is_hidden("#sidechat") and width("#pane-left") == 200
    tab.click("#pane-left button[aria-label='Hide changed files']")
    assert tab.is_hidden("#changes") and width("#scroll") == 1400
    tab.click("header button[aria-label='Show side chats']")
    tab.wait_for_selector("#sidechat .say:has-text('About “why main?”')")
    assert tab.evaluate("document.activeElement.getAttribute('aria-label')") == "Hide side chats"
    assert tab.is_hidden("header button[aria-label='Show side chats']") and tab.is_visible("header button[aria-label='Show changed files']")
    # Narrower: no panels, the side chats open over the chat from their button in the header.
    tab.set_viewport_size({"width": 400, "height": 800})
    assert tab.is_hidden("#sidechat") and tab.is_hidden("header .pane-toggle")
    tab.click("header button[aria-label='Side chats']")
    tab.wait_for_selector("#sidechat .say:has-text('About “why main?”')")
    tab.keyboard.press("Escape")
    tab.wait_for_selector("#sidechat", state="hidden")
