"""The web UI (web/ui: the dashboard, a session's chat, the terminal) in a real browser: the
dashboard, a session's chat from its first moment, tabs, closing, favicons, CI marks, day and night.

The server runs from a copy of src/server with the built pages (web/ui/dist, built first when
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
from test_web import FAKE_CODE, STUB, ui_dist  # noqa: F401 (a fixture)

sync_api = pytest.importorskip("playwright.sync_api")

RUN = "abc123"  # the run the fixture's first pull request and checkout belong to

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
def board(tmp_path, browser, ui_dist):
    sandbox = tmp_path / "sandbox"
    (sandbox / "web/ui").mkdir(parents=True)  # the server and the built pages: not the app's sources or node_modules
    shutil.copytree(REPO / "src/server", sandbox / "src/server", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ui_dist, sandbox / "web/ui/dist")
    shutil.copytree(REPO / "plugins", sandbox / "plugins")
    shutil.copytree(REPO / "agents", sandbox / "agents")
    (sandbox / "src/orchestrator").mkdir(parents=True)
    shutil.copy(REPO / "src/orchestrator/kernel.json", sandbox / "src/orchestrator")
    shutil.copy(REPO / ".claude-sandbox.example.json", sandbox)
    tool(sandbox / "run.sh", STUB.read_text())
    tool(tmp_path / "bin/docker", DOCKER)
    tool(tmp_path / "bin/code", FAKE_CODE)
    project = tmp_path / "proj"
    project.mkdir()
    checkout = tmp_path / f"mirrors/proj-20261112-{RUN}"
    checkout.mkdir(parents=True)
    (tmp_path / "projects").write_text(f"{project}\n")
    proc = subprocess.Popen([sandbox / "src/server/server.py", "--port", "0", "--projects", tmp_path / "projects"],
                            stdout=subprocess.PIPE, text=True,
                            env={"PATH": f"{tmp_path}/bin:/usr/bin:/bin", "HOME": str(tmp_path),
                                 "SHELL": "/bin/sh", "XDG_DATA_HOME": str(tmp_path / "data"), "STUB_BOOT": "0.02"})
    base = proc.stdout.readline().split()[1]
    # Items on another origin, as GitHub's are: localhost is the same server, another origin.
    elsewhere = base.replace("127.0.0.1", "localhost")
    (sandbox / "web.json").write_text(json.dumps({"notes": [], "agent": "claude", "checkout": f"{tmp_path}/mirrors/*-{{run_id}}",
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
            {"project": str(project), "kind": "resume", "run_id": RUN}).encode())
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
    for name in ("New session", "Terminal", "Settings"):  # the project's buttons, on its panel on the right
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


def test_the_project_and_the_start_button_stay_put_while_the_first_message_grows(board):
    button = lambda: board.locator(".starter button[type=submit]").bounding_box()  # noqa: E731
    before, field = button(), board.locator(".starter .field").bounding_box()
    board.fill(".starter textarea", "one\ntwo\nthree\nfour")
    assert board.locator(".starter .field").bounding_box()["height"] > field["height"] + 40
    assert button() == before
    assert board.query_selector(".starter .field button") is None  # beside the field, not in it


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
    stop, card = board.locator(".window button[aria-label='Stop session']").bounding_box(), board.locator(".window").bounding_box()
    assert stop["y"] - card["y"] < 20 and card["x"] + card["width"] - stop["x"] - stop["width"] < 20
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
    board.click(".theme button[aria-label='Day']")  # pinned: the browser's setting no longer decides
    assert paper(board) == day and board.get_attribute(".theme button[aria-label='Day']", "aria-pressed") == "true"
    tab = opens_tab(board, lambda: board.click("button[aria-label='New session']"))
    tab.emulate_media(color_scheme="dark")
    assert tab.evaluate("document.documentElement.dataset.theme") == "light"  # the chat wears it too
    tab.click(".theme button[aria-label='Follow the browser']")
    assert tab.evaluate("document.documentElement.dataset.theme") is None
    assert paper(tab) == "rgb(15, 17, 35)"
    term = opens_tab(board, lambda: board.click("button[aria-label='Terminal']"))
    term.emulate_media(color_scheme="light")
    # and so does the terminal (which comes with xterm.js, loaded after the page itself)
    term.wait_for_function("window.term && term.options.theme.background === '#fbfbfe'")
    term.emulate_media(color_scheme="dark")
    term.wait_for_function("term.options.theme.background === '#0f1123'")


def test_one_terminal_per_project_on_this_machine(board):
    term = opens_tab(board, lambda: board.click("button[aria-label='Terminal']"))
    term.wait_for_selector("header .what:has-text('terminal')")
    term.wait_for_function("decodeURIComponent(document.querySelector('link[rel=icon]').href).includes('<path')")
    term.click(".xterm")
    term.keyboard.type("echo $(basename $PWD)-$((40+2))\n")
    term.wait_for_selector("text=proj-42")  # in the project's directory
    again_opens_nothing(board, lambda: board.click("button[aria-label='Terminal']"))
    assert board.query_selector(".window") is None and board.is_visible(NOBODY)  # a terminal is not a session

    term.keyboard.type("exit 3\n")
    term.wait_for_selector("text=exited 3")  # still there to read, not closed under you
    assert not term.is_closed()


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
    assert "/vscode/?folder=" in code.url
    its_pr = opens_tab(board, lambda: board.click(f"{ROW} a.chip:has-text('#3')"))
    issue = opens_tab(board, lambda: board.click("text=A bug"))
    term = opens_tab(board, lambda: board.click("button[aria-label='Terminal']"))

    delete(board)
    for tab in (session, code, its_pr):
        closes(tab, board)
    assert not issue.is_closed() and not term.is_closed() and not board.is_closed()


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
    session.wait_for_selector(".you:has-text('Fix issue #7 now')")  # the task is the session's first message
    session.wait_for_selector(".say:has-text('Done with “Fix issue #7 now”.')")
    [s] = state(board)
    assert (s["kind"], s["title"]) == ("run", "Fix issue #7 now") and session.url.endswith("/chat#" + s["id"])
    board.wait_for_selector(".window .open:has-text('Fix issue #7 now')")


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
    """Every declared setting gets a control of its type; what the form has none for is kept."""
    file = board.project / ".claude-sandbox.json"
    file.write_text(json.dumps({"env": {"CLAUDE_EFFORT": "high", "GH_USERNAME": "me"},
                                "plugins": {"git-workspace": {"branchPrefix": "bot", "extra": 1}, "retired": {"x": 1}}}))
    board.click("button[aria-label='Settings']")
    board.wait_for_selector("dialog[open] b:has-text('docker-cli')")
    assert board.input_value("input[name='plugins.git-workspace.branchPrefix']") == "bot"
    assert board.get_attribute("input[name='env.GH_HOST']", "placeholder") == "github.com"  # its default
    assert board.input_value("select[name='env.CLAUDE_EFFORT']") == "high"
    assert "extra" in board.text_content(".card:has(button[name='enabled-git-workspace']) .kept")

    # Plugins: a switch each, its settings shown while it is on.
    assert board.get_attribute("button[name='enabled-docker-cli']", "aria-checked") == "true"  # the default
    board.click("button[name='enabled-docker-cli']")
    assert not board.is_visible("textarea[name='plugins.kvm.briefing']")  # kvm is off by default
    board.click("button[name='enabled-kvm']")
    board.fill("textarea[name='plugins.kvm.briefing']", "VMs in /data")
    board.select_option("select[name='env.CLAUDE_EFFORT']", "max")
    board.fill("input[name='env.GH_USERNAME']", "")  # emptied: unset

    # Lists: + Add a row each; one left empty is not saved.
    deps = ".card:has(button[name='enabled-project-deps']) .field:has(label:text-is('apt packages'))"
    board.click(deps + " button.add")
    board.fill("input[name='plugins.project-deps.apt.0']", "ripgrep")
    board.click(deps + " button.add")

    # A route: an object in a list, its auth fields following the type picked.
    routes = ".card:has(button[name='enabled-upstream-proxy'])"
    board.click(routes + " .field:has(label:text-is('Routes')) > .control > .entries > button.add")
    board.fill("input[name='plugins.upstream-proxy.routes.0.name']", "api")
    board.fill("input[name='plugins.upstream-proxy.routes.0.upstream']", "https://api.example.com")
    board.check("input[name='plugins.upstream-proxy.routes.0.allowMethods.GET']")
    assert not board.is_visible("input[name='plugins.upstream-proxy.routes.0.auth.valueEnv']")
    board.select_option("select[name='plugins.upstream-proxy.routes.0.auth.type']", "bearer")
    board.fill("input[name='plugins.upstream-proxy.routes.0.auth.valueEnv']", "API_KEY")
    board.click(routes + " .field:has(> .label label:text-is('Container environment')) > .control button.add")
    board.fill("input[name='plugins.upstream-proxy.routes.0.containerEnv.0.key']", "API_URL")
    board.fill("input[name='plugins.upstream-proxy.routes.0.containerEnv.0.value']", "http://127.0.0.1:8081")
    board.click("dialog button[type=submit]")
    board.wait_for_selector("dialog .error:has-text('routes[0].port is required')")  # the server's check
    assert json.loads(file.read_text())["env"]["GH_USERNAME"] == "me"  # nothing saved
    board.fill("input[name='plugins.upstream-proxy.routes.0.port']", "8081")

    board.click("dialog button[type=submit]")
    board.wait_for_selector("dialog[open]", state="detached")
    assert json.loads(file.read_text()) == {
        "env": {"CLAUDE_EFFORT": "max"},
        "plugins": {"git-workspace": {"branchPrefix": "bot", "extra": 1}, "retired": {"x": 1},
                    "docker-cli": {"enabled": False}, "kvm": {"enabled": True, "briefing": "VMs in /data"},
                    "project-deps": {"apt": ["ripgrep"]},
                    "upstream-proxy": {"routes": [{"name": "api", "upstream": "https://api.example.com",
                                                   "allowMethods": ["GET"], "auth": {"type": "bearer", "valueEnv": "API_KEY"},
                                                   "containerEnv": {"API_URL": "http://127.0.0.1:8081"},
                                                   "port": 8081}]}}}

    board.click("button[aria-label='Settings']")  # opens on what the file holds now
    board.wait_for_selector("dialog[open]")
    assert board.get_attribute("button[name='enabled-docker-cli']", "aria-checked") == "false"
    board.click(".card:has(button[name='enabled-docker-cli']) .reset")  # back to its default: no entry
    assert board.get_attribute("button[name='enabled-docker-cli']", "aria-checked") == "true"
    board.fill("input[type=search]", "branch prefix")  # the filter keeps the matching settings
    assert board.is_visible("input[name='plugins.git-workspace.branchPrefix']")
    assert not board.is_visible("button[name='enabled-kvm']")

    # The JSON view edits the whole file; a typo there is reported, not saved.
    board.click(".modes button:has-text('JSON')")
    text = board.input_value("textarea[name='json']")
    assert '"retired"' in text and "docker-cli" not in text
    board.fill("textarea[name='json']", text.replace('"bot"', '"robot"'))
    board.click(".modes button:has-text('Form')")
    assert board.input_value("input[name='plugins.git-workspace.branchPrefix']") == "robot"
    board.click(".modes button:has-text('JSON')")
    board.fill("textarea[name='json']", "{oops")
    board.click("dialog button[type=submit]")
    board.wait_for_selector("dialog .error:has-text('Not valid JSON')")
    board.fill("textarea[name='json']", text)
    board.click("dialog button[type=submit]")
    board.wait_for_selector("dialog[open]", state="detached")
    assert "docker-cli" not in json.loads(file.read_text())["plugins"]
