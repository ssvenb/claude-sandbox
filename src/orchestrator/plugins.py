"""Which plugins run. A plugin is a directory under plugins/ with a plugin.json manifest and
optional lifecycle scripts, one per privilege stage:

    host.sh        sourced on the host by src/contract/host/stage.sh — validates config, adds docker args
    web.sh         sourced on the host by `run.sh --web` — what the web UI shows for a project
    root-init.sh   sourced by entrypoint.sh as root, where secrets live
    agent-init.sh  sourced by agent-setup.sh as the unprivileged 'node' user

Enablement is resolved ONCE here and handed to the stages and the container as $ENABLED_PLUGINS,
so nothing downstream re-interprets the ENABLE_* flags.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import SANDBOX, Die
from .config import Project, tostring

ON, OFF = {"1", "true", "yes", "on"}, {"0", "false", "no", "off"}


@dataclass
class Plugin:
    name: str
    priority: float = 50
    default_enabled: bool = False
    required_agent: str = ""
    conflicts: list = field(default_factory=list)
    required_env: list = field(default_factory=list)
    provides: list = field(default_factory=list)
    requires: list = field(default_factory=list)


def plugin_root(env: dict) -> Path:
    return Path(env.get("PLUGIN_ROOT") or SANDBOX / "plugins")


def flag_name(plugin: str) -> str:
    """The ENABLE_ flag of a plugin: github-auth → ENABLE_GITHUB_AUTH."""
    return "ENABLE_" + plugin.upper().replace("-", "_")


def discover(root: Path) -> list[Plugin]:
    """Every plugin on disk, in priority order (then by name)."""
    if not root.is_dir():
        raise Die(f"Plugin directory not found: {root}")
    found = []
    for path in sorted(root.glob("*/plugin.json")):
        try:
            m = json.loads(path.read_text())
            if not isinstance(m, dict):
                raise ValueError
        except (ValueError, UnicodeDecodeError):
            raise Die(f"Malformed manifest: {path}") from None
        try:
            priority = m.get("priority")
            found.append(Plugin(path.parent.name, float(50 if priority is None else priority),
                                tostring(m.get("defaultEnabled", False)) == "true", m.get("requiredAgent") or "",
                                *(list(m.get(k) or []) for k in ("conflicts", "requiredEnv", "provides", "requires"))))
        except (TypeError, ValueError):
            raise Die(f"Malformed manifest: {path}") from None
    if not found:
        raise Die(f"No plugins found in {root}")
    return sorted(found, key=lambda p: (p.priority, p.name))


def resolve(plugins: list[Plugin], env: dict, project: Project, agent: str) -> list[Plugin]:
    """The plugins that will run, in priority order. The worked-on repo has the last word, then
    the ENABLE_ flag (already overlaid with the project's own .env, see config.py), then the
    manifest default."""
    enabled = []
    for p in plugins:
        value = project.plugin_setting(p.name, "enabled")
        source = f'{project.config_file} (.plugins["{p.name}"].enabled)'
        if not value:
            value, source = env.get(flag_name(p.name), ""), flag_name(p.name)
        if not value:
            value, source = ("true" if p.default_enabled else "false"), f"{p.name}'s manifest"
        if value in OFF:
            continue
        if value not in ON:
            raise Die(f"{source} must be 0 or 1 (got: {value})")
        # A plugin tied to one agent is silently dropped when another agent runs, rather than failing.
        if p.required_agent and p.required_agent != agent:
            continue
        enabled.append(p)
    return enabled


def validate(enabled: list[Plugin], everything: list[Plugin], env: dict) -> None:
    """Refuses a mix that cannot run: conflicting plugins, unset required settings, a capability
    nobody provides."""
    names = {p.name for p in enabled}
    for p in enabled:
        for other in p.conflicts:
            if other in names:
                raise Die(f"Plugins '{p.name}' and '{other}' cannot be enabled together. Disable one of them "
                          "in .env or in the project's .claude-sandbox.json.")
    provided = set()
    for p in enabled:
        for var in p.required_env:
            if not env.get(var):
                raise Die(f"Plugin '{p.name}' requires {var} to be set in .env or in the project's .claude-sandbox.json")
        provided.update(p.provides)
    for p in enabled:
        for cap in p.requires:
            if cap not in provided:
                providers = ",".join(q.name for q in everything if cap in q.provides)
                raise Die(f"Plugin '{p.name}' requires the '{cap}' capability. "
                          f"Enable one of: {providers or '<none available>'}")
