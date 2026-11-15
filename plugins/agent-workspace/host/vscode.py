#!/usr/bin/env python3
"""VS Code in the browser (`code serve-web`), for opening a run's mirrored checkout: the server the
web server starts on first use and tunnels /plugins/agent-workspace/ to (web_server in ../web.sh),
on the unix socket WEB_SOCKET names, under the base path WEB_BASE. It serves any folder
(`?folder=`), so one is enough for all projects and runs.

VS Code in a browser is a shell on your account. It runs without a connection token: the web
server's tunnel is the only way in, behind its guard (and a token would not survive anyway: the
server refuses its token cookie on any navigation another origin started).
"""
import json
import os
import shutil
import sys
from pathlib import Path

# Machine settings every VS Code tab gets. Copilot's chat pane has no place here: the agent works
# in the sandbox, VS Code is for reading and editing what it did.
SETTINGS = {"chat.disableAIFeatures": True}


def cli():
    """The VS Code CLI that can `serve-web`. Not the desktop `code` launcher where there is one:
    it only passes the command on to the CLI it bundles, and the snap's launcher (which puts
    `--no-sandbox` first) exits 0 without serving at all, so go to that bundled CLI directly."""
    code = shutil.which("code")
    if not code:
        sys.exit("VS Code's `code` command is not installed on this machine")
    for found in (Path(os.path.realpath(code)).with_name("code-tunnel"),  # .deb/.rpm: /usr/share/code/bin
                  Path(code).parent.parent / "code/current/usr/share/code/bin/code-tunnel"):  # snap
        if os.access(found, os.X_OK):
            return str(found)
    return code  # the standalone CLI (code.visualstudio.com/#alt-downloads) is `code` itself


def data():
    """VS Code's data directory (extensions, machine settings), with SETTINGS applied over what is
    already there: settings changed in VS Code itself, under "Remote", are kept."""
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "claude-sandbox/vscode"
    file = data / "data/Machine/settings.json"
    file.parent.mkdir(parents=True, exist_ok=True)
    try:
        settings = json.loads(file.read_text())
    except FileNotFoundError:
        settings = {}
    except ValueError:  # edited in VS Code, with comments: not ours to rewrite
        return data
    if settings | SETTINGS != settings:
        file.write_text(json.dumps(settings | SETTINGS, indent=2) + "\n")
    return data


if __name__ == "__main__":
    code = cli()
    os.execv(code, [code, "serve-web", "--socket-path", os.environ["WEB_SOCKET"], "--without-connection-token",
                    "--server-base-path", os.environ["WEB_BASE"], "--server-data-dir", str(data()),
                    "--accept-server-license-terms"])
