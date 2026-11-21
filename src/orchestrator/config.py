"""Per-project configuration: a project's file, ~/.config/claude-sandbox/projects/<name>.json
(`run.sh --project <name>`), and the settings it layers over your environment.

Configuration is per-project: the file names the repo the agent works on ("repo": a path on this
machine, or a git URL, cloned only in the container) and how it wants to be
sandboxed; the sandbox's own directory contributes nothing. Lowest to highest precedence:

  1. a plugin manifest's defaultEnabled, and each setting's built-in default
  2. anything already exported in your shell
  3. the project's file                     — "env" block, and per-plugin "enabled"
  4. `run.sh --set NAME=VALUE`                — what this one run was started with (by a plugin's
                                                 web_start: a review under another authentication)

The repo's own .env is not read: it is the target repo's, full of its own secrets. The names the
sandbox owns — what the "env" block and --set may set — are every key in .env.example, the
catalogue of them, plus any ENABLE_<PLUGIN> flag.

    ~/.config/claude-sandbox/projects/my-app.json
    {
      "repo": "~/code/my-app",
      "env": { "AGENT": "copilot", "ENABLE_GIT_WORKSPACE": 0 },
      "plugins": {
        "upstream-proxy": { "routes": [ ... ] },
        "git-workspace": { "enabled": false }
      }
    }

The file and every key in it are optional. Nothing here is passed to the container — a plugin
decides what, if anything, crosses over.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import SANDBOX, Die

_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_BLANK = " \t\n\v\f\r"  # bash's [[:space:]]


def scan_env(path, commented=False) -> dict[str, str]:
    """KEY=VALUE lines of a .env file, parsed, never executed. With `commented`, `#KEY=value`
    counts too, which is how .env.example documents optional defaults; without it, comments are
    skipped. It reads .env.example, the catalogue of the sandbox's names."""
    out: dict[str, str] = {}
    try:
        text = Path(path).read_bytes().decode("utf-8", "surrogateescape") if path else None
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        return out
    if text is None:
        return out
    for line in text.split("\n"):
        line = line.removesuffix("\r").lstrip(_BLANK)  # CRLF checkouts, leading blanks
        if commented:
            line = line.removeprefix("#").lstrip(_BLANK)
        elif not line or line.startswith("#"):
            continue
        line = line.removeprefix("export").lstrip(_BLANK)
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.rstrip(_BLANK)
        if not _KEY.fullmatch(key):  # prose that contains '='
            continue
        value = value.strip(_BLANK)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value  # last assignment wins
    return out


def _or(value, default):
    """jq's `value // default`: only null and false fall through."""
    return default if value is None or value is False else value


def tostring(value) -> str:
    """A JSON scalar as jq's tostring spells it, which is how the shell side has always read them."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e17:
        return str(int(value))
    if isinstance(value, (int, float)):
        return repr(value)
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


@dataclass
class Project:
    """What the worked-on repo says about its sandbox."""
    cwd: str
    config_file: str
    config: dict | None = None             # the project's file, when there is one

    def plugin_setting(self, plugin: str, key: str) -> str:
        """One scalar of a plugin's section, "" when unset — as project_plugin_setting reads it."""
        section = _or(_or((self.config or {}).get("plugins"), {}).get(plugin), {})
        if not isinstance(section, dict):
            raise Die(f"Project config '{self.config_file}': .plugins[\"{plugin}\"] must be an object.")
        value = section.get(key)
        return "" if value is None else tostring(value)


def load_project(env: dict) -> Project:
    """The project's file (PROJECT_CONFIG_FILE, which `--project` sets), if any, for the checkout
    at $HOST_CWD."""
    project = Project(env.get("HOST_CWD") or ".", env.get("PROJECT_CONFIG_FILE") or "")
    path = Path(project.config_file)
    if project.config_file and path.is_file():
        where = f"Project config '{project.config_file}'"
        try:
            config = json.loads(path.read_text())
        except (ValueError, UnicodeDecodeError):
            config = None
        if not isinstance(config, dict):
            raise Die(f"{where} must be a JSON object.")
        if not isinstance(_or(config.get("plugins"), {}), dict):
            raise Die(f"{where}: .plugins must be an object keyed by plugin name.")
        block = _or(config.get("env"), {})
        if not isinstance(block, dict) or any(isinstance(v, (dict, list)) for v in block.values()):
            raise Die(f"{where}: .env must be an object of scalar values.")
        project.config = config
    return project


def projects_dir(env: dict) -> Path:
    """Where the projects' files are: a <name>.json each."""
    return Path(env.get("SANDBOX_PROJECTS_DIR") or Path(env.get("HOME") or Path.home()) / ".config/claude-sandbox/projects")


def project_names(directory) -> list[str]:
    """The configured projects: every <name>.json in the directory."""
    return sorted(p.stem for p in Path(directory).glob("*.json") if not p.name.startswith(".") and p.is_file())


def project_file(env: dict, name: str) -> Path:
    if not name or "/" in name or name.startswith("."):
        raise Die(f"'{name}' is not a project name: one is the name of a file in {projects_dir(env)}, without .json")
    path = projects_dir(env) / f"{name}.json"
    if not path.is_file():
        raise Die(f"No project '{name}': there is no {path}")
    return path


_URL = re.compile(r"[a-z][a-z0-9+.-]*://|[\w.-]+@[\w.-]+:")  # https://…, ssh://…, git@github.com:…


def repo_dir(env: dict, name: str, repo) -> str:
    """The project's repo on this machine: its path, or "" for a git URL — nothing is cloned on the
    host; git-workspace clones the URL in the container, with the project's credentials."""
    if not isinstance(repo, str) or not repo.strip():
        raise Die(f"Project '{name}' names no repo: set \"repo\" in its file to a path on this machine or a git URL.")
    if _URL.match(repo):
        return ""
    path = Path(repo).expanduser()
    if not path.is_absolute():
        raise Die(f"Project '{name}': repo '{repo}' must be an absolute path (or ~/…) or a git URL.")
    if not path.is_dir():
        raise Die(f"Project '{name}': repo {path} is not a directory.")
    return str(path)


def sandbox_vars(env: dict) -> set[str]:
    """The names the sandbox owns, besides ENABLE_*: every key .env.example documents."""
    example = env.get("SANDBOX_ENV_EXAMPLE") or str(SANDBOX / ".env.example")
    return set(scan_env(example, commented=True))


# Which plugin started the run (web_start), for its own stages to tell: not a setting of a project's.
STARTED_BY = "SANDBOX_STARTED_BY"


def apply_settings(env: dict, project: Project, sets: dict | None = None) -> list[str]:
    """Lays layers 3 and 4 over `env`, in place, before the agent and the plugins are resolved.
    The names applied, sorted."""
    owned = sandbox_vars(env)

    def owns(name):
        return name.startswith("ENABLE_") or name in owned

    applied = set()
    for key, value in _or((project.config or {}).get("env"), {}).items():
        # This block is written *for* the sandbox, so an unknown name is a typo, not one of the
        # repo's own variables — say so instead of silently ignoring it.
        if not owns(key):
            raise Die(f"Project config '{project.config_file}': .env.{key} is not a sandbox setting (see .env.example).")
        env[key] = tostring(value)
        applied.add(key)
    for key, value in (sets or {}).items():
        if not owns(key) and key != STARTED_BY:
            raise Die(f"--set {key}: not a sandbox setting (see .env.example).")
        env[key] = value
        applied.add(key)
    return sorted(applied)
