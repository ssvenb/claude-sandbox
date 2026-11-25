"""Per-project configuration: a project's file, ~/.config/claude-sandbox/projects/<name>.json
(`run.sh --project <name>`), the one place a project, its agent and its plugins are configured.

The file names the repo the agent works on ("repo": a path on this machine, or a git URL, cloned
only in the container) and how it wants to be sandboxed; the sandbox's own directory contributes
nothing, and neither do your shell's exports nor any .env file. Each setting sits with its owner,
under the key it declares: the sandbox's own at the top, an agent's under "agents", a plugin's
(and whether it is enabled) under "plugins".

    ~/.config/claude-sandbox/projects/my-app.json
    {
      "repo": "~/code/my-app",
      "agent": "copilot",
      "agents": { "claude": { "effort": "high" } },
      "plugins": {
        "upstream-proxy": { "routes": [ ... ] },
        "git-workspace": { "enabled": false, "baseBranch": "trunk" }
      }
    }

A setting the stages read as a variable also declares that variable's name ("env"): run.sh hands
the stages its value under that name, so the plugins' scripts read $BASE_BRANCH as they always
did, while nothing of the kind is taken from your environment. `run.sh --set NAME=VALUE`, by those
names, sets one for a single run (a plugin's web_start: a review under another authentication).

The file and every key in it are optional. Nothing here is passed to the container — a plugin
decides what, if anything, crosses over.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import SANDBOX, Die

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
        if not isinstance(_or(config.get("agents"), {}), dict) \
                or not all(isinstance(v, dict) for v in _or(config.get("agents"), {}).values()):
            raise Die(f"{where}: .agents must be an object of objects keyed by agent name.")
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


ON = {"1", "true", "yes", "on"}


@dataclass
class Owner:
    """The sandbox itself, an agent or a plugin: where its settings sit in a project's file, and
    what it declares."""
    where: tuple            # () for the sandbox's own, ("agents", name), ("plugins", name)
    manifest: dict

    @property
    def settings(self) -> list:
        return [s for s in self.manifest.get("settings") or [] if isinstance(s, dict)]

    def section(self, config: dict) -> dict:
        """Its settings in `config`, {} while it has none."""
        for key in self.where:
            config = config.get(key) if isinstance(config, dict) else None
        return config if isinstance(config, dict) else {}


def declared(env: dict) -> list[Owner]:
    """The sandbox, every agent and every plugin, with what each declares. A manifest that cannot
    be read declares nothing here; discovering the plugins says what is wrong with it."""
    from .agents import agent_root  # noqa: PLC0415 — plugins.py imports this module
    from .plugins import plugin_root  # noqa: PLC0415

    def read(path):
        try:
            found = json.loads(Path(path).read_text())
        except (OSError, ValueError, UnicodeDecodeError):
            return {}
        return found if isinstance(found, dict) else {}
    return ([Owner((), read(SANDBOX / "src/orchestrator/kernel.json"))]
            + [Owner(("agents", p.parent.name), read(p)) for p in sorted(agent_root(env).glob("*/agent.json"))]
            + [Owner(("plugins", p.parent.name), read(p)) for p in sorted(plugin_root(env).glob("*/plugin.json"))])


def owned_names(owners: list[Owner]) -> set[str]:
    """Every variable the stages read a setting from: the declared ones, what an authentication
    fills, what a plugin requires."""
    names = set()
    for o in owners:
        names.update(o.manifest.get("requiredEnv") or [])
        for spec in o.settings:
            names.update(filter(None, [spec.get("env"), *(spec.get("fills") or {}).values()]))
    return names


def without_settings(environ: dict, owners: list[Owner]) -> dict:
    """Your environment, less every name a setting is read from: the project's file is the only
    place they are set."""
    owned = owned_names(owners)
    return {k: v for k, v in environ.items() if k not in owned}


def env_value(spec: dict, value) -> str:
    """A setting's value as its variable holds it: a switch as 1 or 0."""
    if spec.get("type") == "boolean":
        return "1" if value is True or tostring(value).lower() in ON else "0"
    return tostring(value)


# Which plugin started the run (web_start): not a setting of a project's.
STARTED_BY = "SANDBOX_STARTED_BY"


def apply_settings(env: dict, project: Project, sets: dict | None = None) -> list[str]:
    """Lays the project's settings over `env`, in place, as the variables the stages read them
    from, then this run's --set ones, before the agent and the plugins are resolved. Where each
    came from, sorted."""
    owners = declared(env)
    config = project.config or {}
    applied = []
    for owner in owners:
        section = owner.section(config)
        for spec in owner.settings:
            if spec.get("env") and spec.get("key") in section:
                env[spec["env"]] = env_value(spec, section[spec["key"]])
                applied.append(".".join([*owner.where, spec["key"]]))
    owned = owned_names(owners)
    for key, value in (sets or {}).items():
        if key not in owned and key != STARTED_BY:
            raise Die(f"--set {key}: not a sandbox setting.")
        env[key] = value
        applied.append(key)
    return sorted(applied)
