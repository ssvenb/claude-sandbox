"""Which agent runs. An agent is a directory under agents/ packaging one CLI coding agent; exactly
one runs per container, and $AGENT picks it.

    agent.json     manifest, read here before anything else
    install.sh     root, at image build — installs the CLI (only the selected agent's runs)
    host.sh        sourced on the host after every plugin's (src/lib/host-stage.sh)
    agent-init.sh  sourced by agent-setup.sh as 'node' — seeds the agent's own config
    launch.sh      sourced by agent-setup.sh as 'node' — execs the agent with $AGENT_PROMPT
"""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import SANDBOX, Die, say


@dataclass
class Agent:
    name: str
    dir: Path
    manifest: dict


def agent_root(env: dict) -> Path:
    return Path(env.get("AGENT_ROOT") or SANDBOX / "agents")


def resolve_agent(env: dict) -> Agent:
    name = env.get("AGENT") or "claude"
    if not re.fullmatch(r"[a-z0-9-]+", name):
        raise Die(f"Invalid AGENT '{name}' (expected lowercase letters, digits and dashes).")
    root = agent_root(env)
    path = root / name / "agent.json"
    if not path.is_file():
        available = " ".join(sorted(p.parent.name for p in root.glob("*/agent.json")))
        raise Die(f"Unknown agent '{name}'. Available: {available}")
    try:
        manifest = json.loads(path.read_text())
    except (ValueError, UnicodeDecodeError):
        raise Die(f"Malformed manifest: {path}") from None
    return Agent(name, root / name, manifest if isinstance(manifest, dict) else {})


def latest_version(package: str) -> str:
    """The npm registry's latest release of a package; "" when it cannot be reached. Asked directly:
    the host need not have npm installed."""
    try:
        with urllib.request.urlopen(f"https://registry.npmjs.org/{package}/latest", timeout=10) as r:
            return str(json.load(r).get("version") or "").strip()
    except Exception:  # noqa: BLE001 — no answer, for whatever reason, keeps the image's version
        return ""


def resolve_version(agent: Agent, env: dict) -> str:
    """The `AGENT_VERSION` build arg. It is the cache key of the install layer, so resolving the
    latest release here is what makes a new upstream version rebuild that one layer (the
    in-container auto-updater is off, so without this the agent would freeze on an old release).
    Set in .env it pins explicitly; a failed registry lookup leaves it empty, which reuses the image
    as-is rather than failing the run."""
    package = agent.manifest.get("npmPackage")
    if not package:
        return env.get("AGENT_VERSION", "")
    if env.get("AGENT_VERSION"):
        say(f"📌 {package}@{env['AGENT_VERSION']} (pinned)")
        return env["AGENT_VERSION"]
    version = latest_version(package)
    if version:
        say(f"📌 {package}@{version} (latest)")
    else:
        say(f"⚠️  Could not reach the npm registry for {package} — keeping the version already in the image.")
    return version
