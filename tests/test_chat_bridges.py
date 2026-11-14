"""agents/<name>/chat.mjs: each agent's SDK on one side, the sandbox's chat events on the other.

The bridges run for real, under `node`, against stand-ins for the SDKs (tests/stubs/sdk) that
replay a script of what the SDK would say and log how they were called. Skipped without node.
"""
import json
import os
import shutil
import subprocess
import time

import pytest

from conftest import REPO

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="needs node")

RS = "\x1e"


class Bridge:
    """One run of a bridge: `say` sends it a command, `until` reads its events up to one."""

    def __init__(self, agent, tmp, script, **env):
        self.log = tmp / "log"
        self.log.write_text("")
        (tmp / "script").write_text(json.dumps(script))
        (tmp / "work").mkdir(exist_ok=True)
        self.proc = subprocess.Popen(
            ["node", REPO / f"agents/{agent}/chat.mjs"], cwd=tmp / "work", text=True,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={"PATH": os.environ["PATH"], "HOME": str(tmp), "RUN_ID": "0a1b2c",
                 "SANDBOX_LIB": str(REPO / "src/services/chat"), "AGENT_SDK_DIR": str(REPO / "tests/stubs/sdk"),
                 "CLAUDE_BIN": "/opt/claude", "COPILOT_CLI_PATH": "/opt/copilot",
                 "FAKE_LOG": str(self.log), "FAKE_SCRIPT": str(tmp / "script"), **env})
        self.events = []

    def say(self, **command):
        self.proc.stdin.write(json.dumps(command) + "\n")
        self.proc.stdin.flush()

    def until(self, test):
        for line in self.proc.stdout:
            assert line.startswith(RS), f"not an event: {line!r}"  # stdout is the wire, and nothing else
            self.events.append(json.loads(line[1:]))
            if test(self.events[-1]):
                return self.events[-1]
        raise AssertionError(f"it ended first:\n{self.events}\n{self.proc.stderr.read()}")

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def close(self):
        self.proc.stdin.close()
        assert self.proc.wait(10) == 0, self.proc.stderr.read()


def of(events, kind):
    return [e for e in events if e["type"] == kind]


CLAUDE_TURN = [
    {"type": "stream_event", "parent_tool_use_id": None, "event": {"type": "message_start", "message": {"id": "m1"}}},
    {"type": "stream_event", "parent_tool_use_id": None,
     "event": {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking"}}},
    {"type": "stream_event", "parent_tool_use_id": None,
     "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "Hm."}}},
    {"type": "assistant", "parent_tool_use_id": None,
     "message": {"id": "m1", "content": [{"type": "thinking", "thinking": "Hm."}]}},
    {"type": "stream_event", "parent_tool_use_id": None,
     "event": {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "t1", "name": "Bash"}}},
    {"type": "assistant", "parent_tool_use_id": None, "message": {"id": "m1", "content": [
        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]}},
    {"type": "user", "parent_tool_use_id": None, "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "a\nb"}], "is_error": False}]}},
    {"type": "assistant", "parent_tool_use_id": "t1", "message": {"id": "m2", "content": [
        {"type": "tool_use", "id": "t2", "name": "TodoWrite", "input": {"todos": [{"content": "sub", "status": "pending"}]}}]}},
    {"type": "assistant", "parent_tool_use_id": None, "message": {"id": "m3", "content": [
        {"type": "tool_use", "id": "t3", "name": "TodoWrite", "input": {"todos": [
            {"content": "Do it", "activeForm": "Doing it", "status": "in_progress"},
            {"content": "Done it", "status": "completed"}]}}]}},
    {"type": "stream_event", "parent_tool_use_id": None, "event": {"type": "message_start", "message": {"id": "m4"}}},
    {"type": "stream_event", "parent_tool_use_id": None,
     "event": {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}}},
    {"type": "stream_event", "parent_tool_use_id": None,
     "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "All "}}},
    {"type": "stream_event", "parent_tool_use_id": None,
     "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "done."}}},
    {"type": "assistant", "parent_tool_use_id": None, "message": {"id": "m4", "content": [{"type": "text", "text": "All done."}]}},
    {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.25, "duration_ms": 900, "result": "All done."},
    {"type": "prompt_suggestion", "suggestion": "Ship it"},
]


def test_claude_is_started_as_the_terminal_would_and_its_messages_become_chat_events(tmp_path):
    b = Bridge("claude", tmp_path, CLAUDE_TURN, AGENT_PROMPT="Brief.", CLAUDE_EFFORT="high")
    ready = b.until(lambda e: e["type"] == "ready")
    assert b.events[0] == {"type": "hello", "agent": "claude"}
    assert (ready["version"], ready["effort"], ready["account"]) == ("1.2.3", "high", "someone@example.com")
    assert ready["models"] == [{"id": "default", "name": "Default", "description": "Test 1 · Everyday"}]
    assert ready["commands"] == [{"name": "compact", "description": "Summarise", "hint": "[instructions]"}]
    options = b.calls()[0]["options"]
    assert options | {"cwd": ""} == {  # every permission granted, the run's own conversation, the briefing appended
        "cwd": "", "pathToClaudeCodeExecutable": "/opt/claude", "permissionMode": "bypassPermissions",
        "allowDangerouslySkipPermissions": True, "includePartialMessages": True,
        "agentProgressSummaries": True, "effort": "high", "canUseTool": "function", "stderr": "function",
        "systemPrompt": {"type": "preset", "preset": "claude_code", "append": "Brief."},
        "sessionId": "5a4db0c0-0000-4000-8000-0000000a1b2c",
        "env": ["CLAUDE_CODE_EMIT_SESSION_STATE_EVENTS"]}  # or it never says a turn is over
    assert options["cwd"].endswith("/work")

    b.say(type="prompt", text="do it")
    b.until(lambda e: e == {"type": "status", "state": "idle"})
    events = b.events[b.events.index(ready) + 1:]
    assert {"prompt": "do it"} in b.calls()
    assert of(events, "model") == [{"type": "model", "id": "claude-test-1"}]
    thought, said = of(events, "text")
    assert (thought["kind"], thought["text"]) == ("thinking", "Hm.") and (said["kind"], said["text"]) == ("text", "All done.")
    deltas = of(events, "delta")
    assert [d["text"] for d in deltas] == ["Hm.", "All ", "done."]
    assert deltas[0]["id"] == thought["id"] and deltas[1]["id"] == deltas[2]["id"] == said["id"]  # the block they streamed into
    tools = of(events, "tool")
    assert [(t["id"], t["name"], t["input"], t.get("parent")) for t in tools] == [
        ("t1", "Bash", None, None), ("t1", "Bash", {"command": "ls"}, None),   # announced, then with its input
        ("t2", "TodoWrite", {"todos": [{"content": "sub", "status": "pending"}]}, "t1"),  # a subagent's, under its call
        ("t3", "TodoWrite", tools[3]["input"], None)]
    assert of(events, "result") == [{"type": "result", "id": "t1", "output": "a\nb", "error": False}]
    assert of(events, "todos") == [{"type": "todos", "items": [  # the main agent's plan only
        {"text": "Doing it", "status": "active"}, {"text": "Done it", "status": "done"}]}]
    assert of(events, "turn") == [{"type": "turn", "cost": 0.25, "duration": 900, "context": {"used": 1200, "max": 200000}}]
    assert [e["state"] for e in of(events, "status")] == ["working", "working", "idle"]
    assert of(events, "suggestion") == []  # the next prompt the SDK would offer is not asked for, nor passed on

    b.say(type="interrupt")
    b.say(type="model", id="opus")
    b.say(type="effort", level="max")
    b.say(type="effort", level="bogus")  # not a level: ignored
    b.until(lambda e: e["type"] == "effort")
    assert b.calls()[-3:] == [{"interrupt": True}, {"model": "opus"}, {"settings": {"effortLevel": "max"}}]
    b.close()


PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="  # one pixel


def test_claudes_background_tasks_are_listed_whole_each_time_and_one_can_be_stopped(tmp_path):
    shell = {"task_id": "s1", "task_type": "local_bash", "description": "npm run dev"}
    agent = {"task_id": "a1", "task_type": "local_agent", "subagent_type": "Explore", "description": "Check the callers"}
    b = Bridge("claude", tmp_path, [
        {"type": "system", "subtype": "background_tasks_changed", "tasks": [
            shell, agent, {"task_id": "w1", "task_type": "local_bash", "description": "a watcher", "ambient": True}]},
        {"type": "system", "subtype": "task_progress", "task_id": "a1", "tool_use_id": "t9", "description": "Check the callers",
         "summary": "Reading src/app.py"},
        {"type": "system", "subtype": "task_progress", "task_id": "gone", "description": "x", "summary": "Not listed"},
        {"type": "system", "subtype": "background_tasks_changed", "tasks": [shell]},
        {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0, "duration_ms": 1, "result": ""}])
    b.until(lambda e: e["type"] == "ready")
    b.say(type="prompt", text="start them")
    b.until(lambda e: e["type"] == "turn")
    assert [e["items"] for e in of(b.events, "tasks")] == [
        [{"id": "s1", "kind": "shell", "text": "npm run dev"}, {"id": "a1", "kind": "agent", "text": "Check the callers"}],  # no housekeeping
        [{"id": "s1", "kind": "shell", "text": "npm run dev"},
         {"id": "a1", "kind": "agent", "text": "Check the callers", "note": "Reading src/app.py"}],  # what it is at
        [{"id": "s1", "kind": "shell", "text": "npm run dev"}]]
    assert {"type": "progress", "id": "t9", "text": "Reading src/app.py"} in b.events  # and on the call that started it
    b.say(type="task", id="s1")
    b.say(type="effort", level="low")
    b.until(lambda e: e["type"] == "effort")
    assert b.calls()[-2:] == [{"stopTask": "s1"}, {"settings": {"effortLevel": "low"}}]
    b.close()


def test_images_pasted_into_a_prompt_reach_each_agent_as_its_sdk_takes_them(tmp_path):
    picture = {"type": "image/png", "data": PNG}
    turn = [{"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0, "duration_ms": 1, "result": ""}]
    b = Bridge("claude", tmp_path, turn)
    b.until(lambda e: e["type"] == "ready")
    b.say(type="prompt", text="what is this?", images=[picture, {"type": "text/html", "data": "PGI+"}, {"type": "image/png", "data": "<b>"}])
    b.until(lambda e: e["type"] == "turn")
    b.say(type="prompt", text="", images=[picture])
    b.until(lambda e: e["type"] == "turn" and len(of(b.events, "turn")) == 2)
    image = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PNG}}
    assert [c["prompt"] for c in b.calls() if "prompt" in c] == [  # only what is a picture; no empty text
        [image, {"type": "text", "text": "what is this?"}], [image]]
    b.close()

    (tmp_path / "c").mkdir()
    c = Bridge("copilot", tmp_path / "c", [])
    c.until(lambda e: e["type"] == "ready")
    c.say(type="prompt", text="what is this?", images=[picture])
    c.until(lambda e: e["type"] == "status" and e["state"] == "idle" and any("send" in x for x in c.calls()))
    assert {"send": {"prompt": "what is this?", "attachments": [
        {"type": "blob", "data": PNG, "mimeType": "image/png", "displayName": "image 1"}]}} in c.calls()
    c.close()


def test_files_attached_to_a_prompt_are_saved_in_the_sandbox_and_named_in_it(tmp_path):
    turn = [{"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0, "duration_ms": 1, "result": ""}]
    (tmp_path / "tmp").mkdir()
    b = Bridge("claude", tmp_path, turn, TMPDIR=str(tmp_path / "tmp"))
    b.until(lambda e: e["type"] == "ready")
    b.say(type="prompt", text="read it", files=[{"name": "../../notes.txt", "data": "aGk="}, {"name": "bad", "data": "<b>"}])
    b.until(lambda e: e["type"] == "turn")
    [saved] = (tmp_path / "tmp").glob("uploads-*/*")
    assert saved.name == "1-notes.txt" and saved.read_text() == "hi"  # only its last part: nothing lands elsewhere
    assert [c["prompt"] for c in b.calls() if "prompt" in c] == [f"read it\n\nAttached files:\n- {saved}"]
    b.close()


def test_a_claude_that_does_not_report_its_state_is_idle_once_its_turn_ends(tmp_path):
    b = Bridge("claude", tmp_path, CLAUDE_TURN, FAKE_STATELESS="1")
    b.until(lambda e: e["type"] == "ready")
    b.say(type="prompt", text="do it")
    b.until(lambda e: e["type"] == "turn")
    assert b.until(lambda e: e["type"] == "status") == {"type": "status", "state": "idle"}
    b.close()


def test_claudes_question_waits_for_the_pages_answer(tmp_path):
    question = {"questions": [{"question": "Red or blue?", "header": "Colour", "multiSelect": False,
                               "options": [{"label": "Red", "description": "Warm"}, {"label": "Blue", "description": "Cool"}]}]}
    b = Bridge("claude", tmp_path, [{"ask": question}])
    b.until(lambda e: e["type"] == "ready")
    b.say(type="prompt", text="ask")
    asked = b.until(lambda e: e["type"] == "ask")
    assert asked["questions"] == [{"question": "Red or blue?", "header": "Colour", "multi": False,
                                   "options": [{"label": "Red", "description": "Warm"}, {"label": "Blue", "description": "Cool"}]}]
    assert b.until(lambda e: e["type"] == "status")["state"] == "question"
    b.say(type="answer", id=asked["id"], answers={"Red or blue?": "Blue"})
    decided = json.loads(b.until(lambda e: e["type"] == "result")["output"])
    assert decided == {"behavior": "allow", "updatedInput": {**question, "answers": {"Red or blue?": "Blue"}}}
    assert {"type": "asked", "id": asked["id"]} in b.events

    b.say(type="prompt", text="ask again")
    again = b.until(lambda e: e["type"] == "ask" and e["id"] != asked["id"])
    b.say(type="answer", id=again["id"], cancel=True)  # dismissed: Claude is told so, not left waiting
    assert json.loads(b.until(lambda e: e["type"] == "result" and e is not None and "dismissed" in e["output"])["output"])["behavior"] == "deny"
    b.close()


def test_a_resumed_claude_run_replays_its_transcript_and_resumes_the_conversation(tmp_path):
    session = "5a4db0c0-0000-4000-8000-0000000a1b2c"
    transcripts = tmp_path / ".claude/projects" / str(tmp_path / "work").replace("/", "-").replace("_", "-").replace(".", "-")
    transcripts.mkdir(parents=True)
    (transcripts / f"{session}.jsonl").write_text("{}\n")
    history = [
        {"type": "user", "parent_tool_use_id": None, "message": {"content": "Fix the bug"}},
        {"type": "user", "parent_tool_use_id": None, "message": {"content": "<system-reminder>not the user's</system-reminder>"}},
        {"type": "user", "parent_tool_use_id": None, "message": {"content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PNG}}, {"type": "text", "text": "Like this"}]}},
        {"type": "user", "parent_tool_use_id": None,
         "message": {"content": "<command-name>/compact</command-name><command-args>briefly</command-args>"}},
        {"type": "assistant", "parent_tool_use_id": None, "message": {"content": [
            {"type": "text", "text": "Looking."}, {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "a"}}]}},
        {"type": "user", "parent_tool_use_id": None, "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "contents", "is_error": False}]}}]
    b = Bridge("claude", tmp_path, [], RESUME="1", FAKE_HISTORY=json.dumps(history))
    b.until(lambda e: e["type"] == "ready")
    replayed = [e for e in b.events if e["type"] not in ("hello", "ready")]
    assert [(e["type"], e.get("text") or e.get("name") or e.get("output")) for e in replayed] == [
        ("user", "Fix the bug"), ("user", "Like this"), ("user", "/compact briefly"), ("text", "Looking."), ("tool", "Read"), ("result", "contents")]
    assert [e.get("images") for e in of(replayed, "user")] == [None, [{"type": "image/png", "data": PNG}], None]  # with what was pasted into it
    options = next(c["options"] for c in b.calls() if "options" in c)
    assert options["resume"] == session and "sessionId" not in options
    b.close()

    fresh = Bridge("claude", tmp_path, [], RESUME="1", HOME=str(tmp_path / "elsewhere"))  # no transcript kept: a new conversation
    fresh.until(lambda e: e["type"] == "ready")
    assert next(c["options"] for c in fresh.calls() if "options" in c)["sessionId"] == session
    fresh.close()


COPILOT_TURN = [
    {"type": "assistant.turn_start", "data": {}},
    {"type": "assistant.reasoning_delta", "data": {"reasoningId": "r1", "deltaContent": "Hm."}},
    {"type": "assistant.reasoning", "data": {"reasoningId": "r1", "content": "Hm."}},
    {"type": "tool.execution_start", "data": {"toolCallId": "t1", "toolName": "bash", "arguments": {"command": "ls"}}},
    {"type": "tool.execution_partial_result", "data": {"toolCallId": "t1", "partialOutput": "a"}},
    {"type": "tool.execution_complete", "data": {"toolCallId": "t1", "success": True, "result": {"content": "a b", "detailedContent": "a\nb"}}},
    {"type": "tool.execution_start", "data": {"toolCallId": "t2", "toolName": "view", "arguments": "{\"path\": \"x\"}", "parentToolCallId": "t1"}},
    {"type": "tool.execution_complete", "data": {"toolCallId": "t2", "success": False, "error": {"message": "No such file"}}},
    {"type": "session.todos_changed", "data": {}},
    {"type": "session.usage_info", "data": {"currentTokens": 500, "tokenLimit": 64000}},
    {"type": "assistant.message_delta", "data": {"messageId": "m1", "deltaContent": "All "}},
    {"type": "assistant.message", "data": {"messageId": "m1", "content": "All done."}},
    {"type": "session.warning", "data": {"message": "Careful."}},
    {"type": "session.model_change", "data": {"newModel": "gpt-other"}},
]


def test_copilot_is_started_as_the_terminal_would_and_its_events_become_chat_events(tmp_path):
    b = Bridge("copilot", tmp_path, COPILOT_TURN, AGENT_PROMPT="Brief.")
    ready = b.until(lambda e: e["type"] == "ready")
    assert b.events[0] == {"type": "hello", "agent": "copilot"}
    assert (ready["version"], ready["model"], ready["effort"], ready["efforts"]) == ("4.5.6", "gpt-test", "low", ["low", "high"])
    assert ready["models"] == [{"id": "gpt-test", "name": "GPT Test", "description": "1× premium requests", "efforts": ["low", "high"]}]
    assert ready["commands"] == [{"name": "compact", "description": "Summarise", "hint": "focus"}]
    client, create = b.calls()[0]["client"], b.calls()[1]["create"]
    assert client == {"connection": {"kind": "stdio", "path": "/opt/copilot"}}
    assert create | {"workingDirectory": ""} == {  # every permission granted, the run's own session, the briefing appended
        "streaming": True, "workingDirectory": "", "systemMessage": {"mode": "append", "content": "Brief."},
        "onPermissionRequest": True, "onUserInputRequest": "function", "onExitPlanModeRequest": "function",
        "onEvent": "function", "sessionId": "sandbox-0a1b2c", "name": "sandbox-0a1b2c"}

    b.say(type="prompt", text="do it")
    b.until(lambda e: e["type"] == "todos")  # read from the runtime once it says they changed
    events = b.events[b.events.index(ready) + 1:]
    assert {"send": {"prompt": "do it"}} in b.calls()
    assert [(e["kind"], e["text"]) for e in of(events, "text")] == [("thinking", "Hm."), ("text", "All done.")]
    assert [(e["id"], e["text"]) for e in of(events, "delta")] == [("r1", "Hm."), ("m1", "All ")]
    assert [(t["id"], t["name"], t["input"], t.get("parent")) for t in of(events, "tool")] == [
        ("t1", "bash", {"command": "ls"}, None), ("t2", "view", {"path": "x"}, "t1")]
    assert of(events, "result") == [
        {"type": "result", "id": "t1", "output": "a", "partial": True},  # while it runs
        {"type": "result", "id": "t1", "error": False, "output": "a\nb"},
        {"type": "result", "id": "t2", "error": True, "output": "No such file"}]
    assert of(events, "todos") == [{"type": "todos", "items": [
        {"text": "First", "status": "done"}, {"text": "Second", "status": "active"}]}]
    assert of(events, "notice") == [{"type": "notice", "level": "warning", "text": "Careful."}]
    assert of(events, "model") == [{"type": "model", "id": "gpt-other"}]
    [turn] = of(events, "turn")
    assert turn["context"] == {"used": 500, "max": 64000} and turn["duration"] >= 0

    b.say(type="prompt", text="/compact now")  # a slash command is the runtime's to run
    assert b.until(lambda e: e["type"] == "notice" and e["level"] == "info")["text"] == "Compacted."
    b.say(type="prompt", text="/usage")
    assert b.until(lambda e: e["type"] == "text" and "usage" in e["text"])["text"] == "```\nusage\n```"
    b.say(type="interrupt")
    b.say(type="model", id="gpt-other")
    b.say(type="effort", level="high")
    b.until(lambda e: e["type"] == "effort")
    assert b.calls()[-5:] == [{"invoke": {"name": "compact", "input": "now"}}, {"invoke": {"name": "usage"}},
                              {"abort": True}, {"model": "gpt-other"}, {"effort": {"reasoningEffort": "high"}}]
    b.close()


def test_copilots_question_waits_for_the_pages_answer(tmp_path):
    b = Bridge("copilot", tmp_path, [{"ask": {"question": "Red or blue?", "choices": ["Red", "Blue"]}}])
    b.until(lambda e: e["type"] == "ready")
    b.say(type="prompt", text="ask")
    asked = b.until(lambda e: e["type"] == "ask")
    assert asked["questions"] == [{"question": "Red or blue?", "header": "", "multi": False, "freeform": True,
                                   "options": [{"label": "Red", "description": ""}, {"label": "Blue", "description": ""}]}]
    b.say(type="answer", id=asked["id"], answers={"Red or blue?": "Green"})
    answered = b.until(lambda e: e["type"] == "text" and e["id"] == "answered")
    assert json.loads(answered["text"]) == {"answer": "Green", "wasFreeform": True}  # not one of its choices
    b.close()


def test_a_resumed_copilot_run_replays_its_session_or_starts_a_new_one(tmp_path):
    history = [{"type": "user.message", "data": {"content": "Fix the bug"}},
               {"type": "assistant.turn_start", "data": {}},
               {"type": "assistant.message", "data": {"messageId": "m0", "content": "Fixed."}},
               {"type": "session.idle", "data": {}}]
    b = Bridge("copilot", tmp_path, [], RESUME="1", FAKE_HISTORY=json.dumps(history))
    b.until(lambda e: e["type"] == "ready")
    assert [(e["type"], e.get("text")) for e in b.events if e["type"] not in ("hello", "ready")] == [
        ("user", "Fix the bug"), ("text", "Fixed.")]  # no turn, no status: that was then
    assert {"resume": "sandbox-0a1b2c"} in b.calls() and not any("create" in c for c in b.calls())
    b.close()

    fresh = Bridge("copilot", tmp_path, [], RESUME="1")  # no session by that name: a new one, under it
    fresh.until(lambda e: e["type"] == "ready")
    assert [next(iter(c)) for c in fresh.calls()] == ["client", "resume", "create"]
    fresh.close()


def test_a_turn_the_api_failed_is_tried_again_until_the_user_steps_in(tmp_path):
    failed = [{"type": "assistant", "parent_tool_use_id": None, "error": "server_error",
               "message": {"id": "m1", "content": [{"type": "text", "text": "API Error: 529 Overloaded."}]}},
              {"type": "result", "subtype": "success", "is_error": True, "total_cost_usd": 0, "duration_ms": 1, "result": "API Error"}]
    b = Bridge("claude", tmp_path, failed, API_RETRY_SECONDS="1")
    b.until(lambda e: e["type"] == "ready")
    b.say(type="prompt", text="do it")
    b.until(lambda e: len(of(b.events, "turn")) == 2)  # the prompt, then a retry on its own
    b.say(type="interrupt")  # a stop, a second before the next retry, ends the retrying
    time.sleep(1.5)
    b.close()
    prompts = [c["prompt"] for c in b.calls() if "prompt" in c]
    assert prompts == ["do it", prompts[1]] and prompts[1].startswith("<api-retry>")
    assert any(e["type"] == "notice" and "trying again" in e["text"] for e in b.events)
