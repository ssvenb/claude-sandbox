#!/usr/bin/env python3
"""VS Code in the browser (`code serve-web`), for opening a run's mirrored checkout: the server the
web server starts on first use and tunnels /plugins/agent-workspace/ to (web_server in ../web.sh),
on the unix socket WEB_SOCKET names, under the base path WEB_BASE. It serves any folder
(`?folder=`), so one is enough for all projects and runs.

VS Code in a browser is a shell, and the folders it opens are the agent's: their .vscode/ and
.git/config run code once trusted or used. So it runs in a container of its own (../vscode.Dockerfile),
not on this machine: as you (so the mirrors stay yours), with no capabilities, and with nothing
mounted but the mirrors, its data directory and the socket's directory. Its terminal, tasks and git
are a shell in there. It runs without a connection token: the web server's tunnel is the only way
in, behind its guard (and a token would not survive anyway: the server refuses its token cookie on
any navigation another origin started).

`vscode.py <mirrors>` starts that container, building its image first; inside, `vscode.py --serve`
applies SETTINGS and becomes `code serve-web`.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

# Settings every VS Code tab gets, by the file under the data directory they go in. Copilot's chat
# pane has no place here: the agent works in the sandbox, VS Code is for reading and editing what it
# did. Workspace trust is application-scoped, so it is only read from the user's settings.
SETTINGS = {
    "Machine": {"chat.disableAIFeatures": True},
    "User": {
        "security.workspace.trust.enabled": True,  # off would trust every folder
        "security.workspace.trust.startupPrompt": "never",  # no dialog whose button trusts the folder
        "security.workspace.trust.banner": "always",
    },
}
IMAGE = "claude-sandbox-vscode"
HERE = Path(__file__).resolve().parent


def data(data):
    """VS Code's data directory (extensions, settings), with SETTINGS applied over what is already
    there: other settings changed in VS Code itself are kept. Run in the container: the directory
    is its to write, so this machine never follows what it planted there."""
    for scope, ours in SETTINGS.items():
        file = data / f"data/{scope}/settings.json"
        file.parent.mkdir(parents=True, exist_ok=True)
        try:
            settings = json.loads(file.read_text())
        except FileNotFoundError:
            settings = {}
        except ValueError:  # edited in VS Code, with comments: not ours to rewrite
            continue
        if settings | ours != settings:
            file.write_text(json.dumps(settings | ours, indent=2) + "\n")
    return data


def run(mirrors, store):
    """The `docker run` of VS Code's container. The mirrors and the socket keep their paths, so
    `?folder=` and WEB_SOCKET mean the same in there."""
    sockets = os.path.dirname(os.environ["WEB_SOCKET"])
    return ["docker", "run", "--rm", "--init", "--name", f"{IMAGE}-{os.getuid()}",
            "--user", f"{os.getuid()}:{os.getgid()}", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "-e", "HOME=/data", "-e", "WEB_SOCKET", "-e", "WEB_BASE",
            "-v", f"{store}:/data", "-v", f"{mirrors}:{mirrors}", "-v", f"{sockets}:{sockets}",
            "-v", f"{HERE}:/opt/vscode:ro", IMAGE, "python3", "/opt/vscode/vscode.py", "--serve"]


def main(argv):
    if argv == ["--serve"]:  # in the container
        os.execvp("code", ["code", "serve-web", "--socket-path", os.environ["WEB_SOCKET"],
                           "--without-connection-token", "--server-base-path", os.environ["WEB_BASE"],
                           "--server-data-dir", str(data(Path("/data"))), "--cli-data-dir", "/data/cli",
                           "--accept-server-license-terms"])
    [mirrors] = argv
    store = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "claude-sandbox/vscode"
    for host_dir in (mirrors, store):
        os.makedirs(host_dir, exist_ok=True)  # or docker creates them, as root
    with open(HERE.parent / "vscode.Dockerfile", "rb") as dockerfile:
        subprocess.run(["docker", "build", "-q", "-t", IMAGE, "-"], stdin=dockerfile, check=True)
    subprocess.run(["docker", "rm", "-f", f"{IMAGE}-{os.getuid()}"], capture_output=True)  # a server before this one's
    os.execvp("docker", run(mirrors, store))


if __name__ == "__main__":
    main(sys.argv[1:])
