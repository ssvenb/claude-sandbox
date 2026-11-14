"""Per-project configuration: the worked-on repo's .claude-sandbox.json and .env, and the settings
they layer over your environment.

Configuration is per-project: a checkout carries the way it wants to be sandboxed, and the
sandbox's own directory contributes nothing. Lowest to highest precedence:

  1. a plugin manifest's defaultEnabled, and each setting's built-in default
  2. anything already exported in your shell
  3. the worked-on repo's .env               — sandbox-owned keys only
  4. the worked-on repo's .claude-sandbox.json — "env" block, and per-plugin "enabled"

Layer 3 is filtered because that file is the target repo's, full of its own secrets: only names
the sandbox owns are lifted out of it, so a stray pass_env cannot forward the repo's API keys into
the container. "Owned" is every key in .env.example plus any ENABLE_<PLUGIN> flag.

    .claude-sandbox.json
    {
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
    skipped. The same parser as env_scan_into in src/lib/host-project-env.sh, which plugins use."""
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
    env_file: str
    config: dict | None = None             # .claude-sandbox.json, when there is one
    dotenv: dict = field(default_factory=dict)  # its .env, scanned: read by plugins with project_env

    def plugin_setting(self, plugin: str, key: str) -> str:
        """One scalar of a plugin's section, "" when unset — as project_plugin_setting reads it."""
        section = _or(_or((self.config or {}).get("plugins"), {}).get(plugin), {})
        if not isinstance(section, dict):
            raise Die(f"Project config '{self.config_file}': .plugins[\"{plugin}\"] must be an object.")
        value = section.get(key)
        return "" if value is None else tostring(value)


def load_project(env: dict) -> Project:
    """The project's .claude-sandbox.json (PROJECT_CONFIG_FILE) and .env (PROJECT_ENV_FILE), next
    to its checkout ($HOST_CWD) unless those say otherwise."""
    cwd = env.get("HOST_CWD") or "."
    project = Project(cwd, env.get("PROJECT_CONFIG_FILE") or f"{cwd}/.claude-sandbox.json",
                      env.get("PROJECT_ENV_FILE") or f"{cwd}/.env")
    path = Path(project.config_file)
    if path.is_file():
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
    project.dotenv = scan_env(project.env_file)
    return project


def sandbox_vars(env: dict) -> set[str]:
    """The names the sandbox owns, besides ENABLE_*: every key .env.example documents."""
    example = env.get("SANDBOX_ENV_EXAMPLE") or str(SANDBOX / ".env.example")
    return set(scan_env(example, commented=True))


def apply_settings(env: dict, project: Project) -> list[str]:
    """Lays layers 3 and 4 over `env`, in place, before the agent and the plugins are resolved.
    The names applied, sorted."""
    owned = sandbox_vars(env)

    def owns(name):
        return name.startswith("ENABLE_") or name in owned

    applied = set()
    for key, value in project.dotenv.items():
        if owns(key):
            env[key] = value
            applied.add(key)
    for key, value in _or((project.config or {}).get("env"), {}).items():
        # This block is written *for* the sandbox, so an unknown name is a typo, not one of the
        # repo's own variables — say so instead of silently ignoring it.
        if not owns(key):
            raise Die(f"Project config '{project.config_file}': .env.{key} is not a sandbox setting (see .env.example).")
        env[key] = tostring(value)
        applied.add(key)
    return sorted(applied)
