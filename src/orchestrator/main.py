"""run.sh: build and launch a coding-agent sandbox container. Runs on YOUR machine, where the
long-lived credentials stay; the container only ever receives what the agent and the enabled
plugins hand it. Configuration is project-specific: it comes from the repo you launch from (.env,
.claude-sandbox.json — see config.py), never from the sandbox's own directory.
"""
from __future__ import annotations

import datetime
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys

from . import SANDBOX, Die, say
from .agents import resolve_agent, resolve_version
from .config import apply_settings, load_project
from .plugins import discover, plugin_root, resolve, validate
from services.ports.lease import Ports, items_file, settings as port_settings
from .stage import Stage, StageFailed, environ

USAGE = ("Usage: {} [--resume <RUN_ID> | --run-id <RUN_ID> | --web | --web-action <PLUGIN> <ACTION> <ARG>] "
         "[--task TEXT] [--chat]   (RUN_ID is 6 hex chars)")


class Usage(Exception):
    def __init__(self, message="", code=1):
        super().__init__(message)
        self.code = code


def parse(argv: list[str]) -> dict:
    opts = {"resume": False, "web": None, "action": None, "task": "", "chat": False, "run_id": None}
    i = 0
    while i < len(argv):
        arg = argv[i]
        # --run-id starts a FRESH run under an id the caller picked (src/server/server.py does, to know
        # which run a session is before the container says so); --resume re-attaches to one.
        if arg in ("--resume", "--run-id"):
            opts["resume"] = opts["resume"] or arg == "--resume"
            opts["run_id"] = argv[i + 1] if i + 1 < len(argv) else ""
            i += 2
        # Starts nothing: prints, as JSON, what the project's enabled plugins have for the web UI.
        elif arg == "--web":
            opts["web"] = "describe"
            i += 1
        # Starts nothing either: does what an item's `on_delete` names, once the web UI's user
        # said yes to it (closing a deleted session's pull request).
        elif arg == "--web-action":
            if len(argv) - i < 4:
                raise Usage("--web-action needs a plugin, an action and its argument.")
            opts["web"], opts["action"] = "action", argv[i + 1:i + 4]
            i += 4
        # The agent's first message, so it starts working without anyone typing (Resolve).
        elif arg == "--task":
            opts["task"] = argv[i + 1] if i + 1 < len(argv) else ""
            i += 2
            if not opts["task"]:
                raise Usage("--task needs the task's text.")
        # No terminal: the agent runs behind its chat bridge (agents/<name>/chat.mjs) and this
        # process's stdin and stdout carry the chat's commands and events (src/services/chat/chat-bridge.mjs).
        # What the web UI starts; prompts arrive as commands, so there is no --task with it.
        elif arg == "--chat":
            opts["chat"] = True
            i += 1
        elif arg in ("-h", "--help"):
            raise Usage(code=0)
        else:
            raise Usage(f"Unknown argument: {arg}")
    if opts["task"] and opts["chat"]:
        raise Usage("--chat takes its prompts as commands; it has no --task.")
    if opts["task"] and opts["resume"]:
        raise Usage("--task starts a fresh run; it cannot resume one.")
    if opts["run_id"] is not None and not (len(opts["run_id"]) == 6
                                           and all(c in "0123456789abcdef" for c in opts["run_id"])):
        raise Usage(f"Invalid RUN_ID '{opts['run_id']}' (expected 6 lowercase hex chars).")
    return opts


def run(opts: dict) -> int:
    env = dict(os.environ)
    # The directory you launched from is the repo the agent works on — plugins read it as
    # $HOST_CWD, never as $PWD.
    env["HOST_CWD"] = os.getcwd()
    os.chdir(SANDBOX)
    # One id and date key the run; --resume and --run-id bring their own. 6 lowercase hex chars,
    # DNS-safe. Both are core, so any plugin's host stage can name its per-run artifacts the same way.
    env["RUN_ID"] = opts["run_id"] or secrets.token_hex(3)
    env["RUN_DATE"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
    web = opts["web"]
    # --web answers with one JSON document on stdout, so everything else said on the way goes to stderr.
    out = sys.stderr if web else sys.stdout

    # The worked-on repo's own files overlay .env before anything reads it, so even AGENT and the
    # plugin mix are per-project.
    project = load_project(env)
    if project.config is not None:
        say(f"📄 Project config: {project.config_file}", file=out)
    applied = apply_settings(env, project)
    if applied:
        say(f"⚙️  Project settings: {' '.join(applied)}", file=out)

    # Agent first: plugins declaring a different requiredAgent are dropped from the run.
    agent = resolve_agent(env)
    env["AGENT"] = agent.name
    everything = discover(plugin_root(env))
    enabled = resolve(everything, env, project, agent.name)
    names = [p.name for p in enabled]
    if not shutil.which("jq"):
        raise Die("jq is required on the host: the plugins' stages read their settings with it.")
    stage_env = environ(env, config=project.config, agent_dir=agent.dir, enabled=names,
                        resume="1" if opts["resume"] else "0")

    if web == "action":
        Stage("web-action", stage_env, *opts["action"], stdout=sys.stderr).finish()
        print("{}", flush=True)
        return 0
    if web:
        # Resolved exactly as a run would be, but not validated: a project that cannot start yet
        # (no App key, say) still has pull requests to show.
        stage = Stage("web", stage_env, stdout=sys.stderr)
        stage.finish()
        said = stage.report.web
        said["live"] = said.get("live", []) + [items_file(env)]
        print(json.dumps({**said, "agent": agent.name, "plugins": names}, separators=(",", ":"),
                         ensure_ascii=False), flush=True)
        return 0

    if opts["chat"] and not (agent.dir / "chat.mjs").is_file():
        raise Die(f"The {agent.name} agent has no chat bridge (agents/{agent.name}/chat.mjs): start it without --chat.")
    validate(enabled, everything, env)
    port_settings(env)  # refused before any plugin sets anything up

    # The agent's host stage comes last, so a plugin bringing credentials of its own
    # (AGENT_AUTH_PROVIDED=1) is already accounted for.
    stage = Stage("host", stage_env)
    ports = None
    try:
        env = stage.report.env
        docker_args = list(stage.report.docker)
        # Whatever the agent serves reaches you through the central port proxy (src/services/ports).
        ports = Ports(env, env["RUN_ID"])
        docker_args += ports.start()
        say(f"🤖 Agent: {agent.name}")
        say(f"🔌 Plugins: {' '.join(names) or '<none>'}")

        # Agent, plugin mix and CLI version are all build args, so the image rebuilds exactly when
        # one of them changes and is fully cached otherwise.
        image = f"claude-agent:{agent.name}"
        version = resolve_version(agent, env)
        built = subprocess.call(["docker", "build", "-t", image, "--build-arg", f"AGENT={agent.name}",
                                 "--build-arg", f"AGENT_VERSION={version}",
                                 "--build-arg", f"ENABLED_PLUGINS={' '.join(names)}",
                                 *stage.report.build, "."], env=env)
        if built:
            return built

        # A chat has no terminal to attach: its stdio is the bridge's wire, which a pty would mangle.
        tty = ["-i", "-e", "AGENT_UI=chat"] if opts["chat"] else ["-it"]
        task = ["-e", f"AGENT_TASK={opts['task']}"] if opts["task"] else []
        container = subprocess.Popen(
            ["docker", "run", *tty, "--rm", "-e", f"RUN_ID={env['RUN_ID']}", "-e", f"RUN_DATE={env['RUN_DATE']}",
             "-e", f"RESUME={'1' if opts['resume'] else '0'}", "-e", f"AGENT={agent.name}",
             "-e", f"ENABLED_PLUGINS={' '.join(names)}", *task, *docker_args,
             "--name", f"sandbox-{env['RUN_ID']}", image], env=env)
        # Not subprocess.run: a signal that ends this process must leave the docker client be, as
        # it always has (the web UI removes the container by name).
        code = container.wait()
        return code if code >= 0 else 128 - code
    finally:
        if ports:
            ports.release()
        stage.finish()


def _terminate(signum, _frame):
    raise SystemExit(128 + signum)


def main(argv=None) -> int:
    prog = os.environ.pop("SANDBOX_RUN_SH", "run.sh")
    try:
        opts = parse(sys.argv[1:] if argv is None else argv)
    except Usage as e:
        if str(e):
            print(str(e), file=sys.stderr)
        print(USAGE.format(prog), file=sys.stderr)
        return e.code
    # Cleanup (the stage's exit hooks, leaving the port proxy) on the way out however this ends:
    # the web UI stops a session with a SIGHUP to its process group.
    for sig in (signal.SIGHUP, signal.SIGTERM):
        signal.signal(sig, _terminate)
    try:
        return run(opts)
    except StageFailed as e:
        return e.code  # the stage said why
    except Die as e:
        print(f"❌ {e}", file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
