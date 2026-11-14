#!/usr/bin/env python3
"""Stands in for run.sh under the web UI's tests (and for looking at the pages without Docker).

`--web` prints web.json from next to it, `--web-action` is logged to `actions`. A session without
`--chat` is the old terminal "agent": it says it has a question, waits for a line, exits 4. With
`--chat` it is a sandbox that boots (a few lines of output, STUB_BOOT seconds apart), then an
agent behind a chat bridge, speaking src/services/chat/chat-bridge.mjs on stdio (the boot waits for as long
as a file `hold` lies next to this one): each prompt gets a turn
that thinks, runs tools and answers. What the prompt says picks the turn:

    "ask"   it asks a question with two choices and says which was picked
    "fail"  a tool fails and the turn ends in an error
    "long"  it keeps working until interrupted
    "background"  it leaves two tasks running in the background, until each is stopped
    "exit"  the sandbox goes away with status 3
"""
import base64
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
args = sys.argv[1:]


def emit(**event):
    sys.stdout.write("\x1e" + json.dumps(event) + "\n")
    sys.stdout.flush()


def say(block, text, **more):
    for word in text.split(" "):
        emit(type="delta", id=block, kind=more.get("kind", "text"), text=word + " ")
        time.sleep(PACE)
    if more.get("whole", True):
        emit(type="text", id=block, kind=more.get("kind", "text"), text=text)


if args[:1] == ["--web"]:
    print((HERE / "web.json").read_text())
    sys.exit(0)
if args[:1] == ["--web-action"]:
    with open(HERE / "actions", "a") as f:
        f.write(" ".join(args[1:4]) + "\n")
    print("{}")
    sys.exit(0)
if "--chat" not in args:
    task = args[args.index("--task") + 1] if "--task" in args else ""
    print(f"agent {args[1]} at work" + (f" on: {task}" if task else ""), flush=True)
    sys.stdout.write("\033]1337;SetUserVar=agent_status=%s\007" % base64.b64encode(b"question").decode())
    sys.stdout.flush()
    sys.stdin.readline()
    sys.exit(4)

BOOT = float(os.environ.get("STUB_BOOT", "0.05"))
PACE = float(os.environ.get("STUB_PACE", "0"))
run_id, resumed = args[1], args[0] == "--resume"
for line in ("🤖 Agent: claude", "🔌 Plugins: github-auth git-workspace", "#1 [internal] load build definition",
             "#2 [5/9] RUN npm install -g @anthropic-ai/claude-code", "#3 exporting to image", "🔐 gh auth login",
             f"📥 Cloning into /workspace on claude-code/20261113-{run_id}"):
    print(line, flush=True)
    time.sleep(BOOT)
while (HERE / "hold").exists():  # a test holds the boot here, to act while the sandbox still starts
    time.sleep(0.02)
if os.environ.get("STUB_BOOT_FAILS"):
    print("❌ GH_PRIVATE_KEY_FILE not found: /nowhere/key.pem", flush=True)
    sys.exit(1)
emit(type="hello", agent="claude")
time.sleep(BOOT)
if resumed:
    emit(type="user", text="What was said before the resume")
    emit(type="text", id="h1", kind="text", text="An earlier answer.")
emit(type="ready", agent="claude", version="9.9.9", model="fable", effort="medium", efforts=["low", "medium", "high"],
     models=[{"id": "fable", "name": "Fable", "description": "Fable 5.2 · Most capable"},
             {"id": "opus", "name": "Opus", "description": "Opus 5.5 · Everyday work"}],
     commands=[{"name": "compact", "description": "Summarise the conversation so far", "hint": "[instructions]"},
               {"name": "review", "description": "Review the changes on this branch", "hint": ""},
               {"name": "context", "description": "Show what fills the context window", "hint": ""}])
emit(type="status", state="idle")

stop = threading.Event()
answers = {}
tasks = []  # what runs in the background
turns = 0


def turn(text):
    global turns
    turns += 1
    n = turns
    emit(type="status", state="working")
    # In a "long" turn its thinking only streams, never sent whole, as Claude's sometimes is.
    say(f"t{n}", "The user wants this done; look at the code first.", kind="thinking", whole="long" not in text)
    emit(type="tool", id=f"r{n}", name="Read", input={"file_path": "/workspace/src/app.py"})
    time.sleep(PACE * 3)
    emit(type="result", id=f"r{n}", output="def main():\n    return 1\n", error=False)
    if "exit" in text:
        os._exit(3)
    if "long" in text:
        emit(type="tool", id=f"b{n}", name="Bash", input={"command": "sleep 600", "description": "Wait a long time"})
        stop.wait()
        stop.clear()
        emit(type="result", id=f"b{n}", output="Interrupted", error=True)
        emit(type="notice", level="info", text="Interrupted.")
    elif "background" in text:
        emit(type="tool", id=f"b{n}", name="Bash", input={"command": "npm run dev", "run_in_background": True})
        emit(type="result", id=f"b{n}", output="Command running in background", error=False)
        tasks.extend([{"id": f"bg{n}a", "kind": "shell", "text": "npm run dev"},
                      {"id": f"bg{n}b", "kind": "agent", "text": "Check the callers", "note": "Reading src/app.py"}])
        emit(type="tasks", items=tasks)
        say(f"a{n}", "Both run in the background.")
    elif "ask" in text:
        emit(type="ask", id=f"q{n}", questions=[{"question": "Which database?", "header": "Storage", "multi": False,
             "options": [{"label": "SQLite", "description": "One file, no server."},
                         {"label": "Postgres", "description": "A server of its own."}]}])
        emit(type="status", state="question")
        while f"q{n}" not in answers:
            time.sleep(0.02)
        emit(type="asked", id=f"q{n}")
        emit(type="status", state="working")
        picked = answers[f"q{n}"]
        say(f"a{n}", "Dismissed, so I chose myself." if picked is None else f"Going with **{picked.get('Which database?')}**.")
    elif "fail" in text:
        emit(type="tool", id=f"b{n}", name="Bash", input={"command": "npm test"})
        emit(type="result", id=f"b{n}", output="1 failing\n  AssertionError: expected 1 to equal 2", error=True)
        emit(type="turn", duration=1200, cost=0.1 * n, error="The API did not answer.")
        return emit(type="status", state="idle")
    else:
        emit(type="todos", items=[{"text": "Read the code", "status": "done"}, {"text": "Changing main()", "status": "active"},
                                  {"text": "Run the tests", "status": "pending"}])
        emit(type="tool", id=f"e{n}", name="Edit", input={"file_path": "/workspace/src/app.py",
             "old_string": "def main():\n    return 1\n", "new_string": "def main():\n    return 2\n"})
        emit(type="result", id=f"e{n}", output="The file has been updated.", error=False)
        emit(type="tool", id=f"s{n}", name="Agent", input={"description": "Check the callers", "prompt": "Find every caller of main()"})
        emit(type="tool", id=f"s{n}g", name="Grep", input={"pattern": "main\\(", "path": "src"}, parent=f"s{n}")
        emit(type="result", id=f"s{n}g", output="src/app.py:1", error=False)
        emit(type="result", id=f"s{n}", output="One caller, in src/app.py.", error=False)
        emit(type="tool", id=f"b{n}", name="Bash", input={"command": "python -m pytest -q", "description": "Run the tests"})
        time.sleep(PACE * 3)
        emit(type="result", id=f"b{n}", output="3 passed in 0.12s", error=False)
        emit(type="todos", items=[{"text": "Read the code", "status": "done"}, {"text": "Change main()", "status": "done"},
                                  {"text": "Run the tests", "status": "done"}])
        say(f"a{n}", f"Done with “{text}”.\n\n## What changed\n\n- `main()` now returns **2**\n- the tests pass\n\n"
                     "| File | Change |\n|---|---|\n| `src/app.py` | one line |\n\n```python\ndef main():\n    return 2\n```\n\n"
                     "See [the docs](https://example.com/docs) for more.")
    emit(type="turn", duration=4200, cost=0.1 * n, context={"used": 30000 * n, "max": 1000000})
    emit(type="status", state="idle")


# One turn at a time, as an agent takes them: a prompt sent meanwhile waits for its own.
prompts = queue.Queue()
threading.Thread(target=lambda: [turn(text) for text in iter(prompts.get, None)], daemon=True).start()

for line in sys.stdin:
    try:
        command = json.loads(line)
    except ValueError:
        continue
    with open(HERE / "commands", "a") as f:
        f.write(json.dumps(command) + "\n")
    if command["type"] == "prompt":
        prompts.put(command["text"])
    elif command["type"] == "interrupt":
        stop.set()
    elif command["type"] == "answer":
        answers[command["id"]] = None if command.get("cancel") else command.get("answers")
    elif command["type"] in ("model", "effort"):
        emit(**command)
    elif command["type"] == "task":
        tasks[:] = [t for t in tasks if t["id"] != command["id"]]
        emit(type="tasks", items=tasks)
