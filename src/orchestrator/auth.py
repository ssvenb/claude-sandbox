"""Authentications: every identity, key and token a sandbox may use, configured once on YOUR
machine, outside every project, each under a name:

    ~/.config/claude-sandbox/auth.json        (SANDBOX_AUTH_FILE points somewhere else; chmod 600)
    {
      "coder":    {"type": "github-app", "appId": "123456", "privateKeyFile": "~/keys/coder.pem"},
      "reviewer": {"type": "github-app", "appId": "234567", "privateKeyFile": "~/keys/reviewer.pem"},
      "data":     {"type": "gcp-service-account", "serviceAccount": "sandbox@my-project.iam.gserviceaccount.com"},
      "openai":   {"type": "api-key", "key": "sk-…"}
    }

TYPES lists what each type holds. Projects and plugins never hold any of it: a plugin or an agent
declares a setting of type "auth" that only names an entry, and which of its own (internal)
variables each field of the entry fills:

    {"key": "auth", "env": "GH_AUTH", "type": "auth", "auth": "github-app",
     "fills": {"appId": "GH_APP_ID", "privateKeyFile": "GH_PRIVATE_KEY_FILE"}}

With GH_AUTH=reviewer its stages run with GH_APP_ID and GH_PRIVATE_KEY_FILE set from that entry, so
they need not know. A setting of type "auth" without `fills` names an entry its owner reads itself
(upstream-proxy's routes, whose host proxy reads the file; run.sh hands every stage its path as
SANDBOX_AUTH_FILE). The web UI offers the names of the entries of the right type.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import Die
from .config import tostring

# Each type: its required fields, then its optional ones. A field ending in "File" is a path on
# this machine, `~` expanded.
TYPES = {
    "github-app": (("appId", "privateKeyFile"), ("host", "username")),
    "gcp-service-account": ((), ("serviceAccount", "project", "credentialFile")),
    "api-key": (("key",), ()),
    "oauth2-client": (("tokenUrl", "clientId", "clientSecret"), ("audience",)),
    "netbird-setup-key": (("key",), ("managementUrl",)),
    "ssh-key": (("privateKeyFile",), ("knownHostsFile", "user")),
    "claude-token": (("token",), ()),
    "copilot-token": (("token",), ()),
}

# The fields that hold a secret itself rather than where one is: the web UI never sends them back.
SECRETS = ("key", "token", "clientSecret")


def auth_file(env: dict) -> Path:
    return Path(env.get("SANDBOX_AUTH_FILE")
                or Path(env.get("XDG_CONFIG_HOME") or Path(env.get("HOME") or Path.home()) / ".config")
                / "claude-sandbox/auth.json")


def load(env: dict) -> dict:
    """Every entry of the file, {} without one. Refused while anyone but you may read it: it holds
    keys and tokens."""
    path = auth_file(env)
    try:
        if path.stat().st_mode & 0o077:
            raise Die(f"Authentications '{path}' hold keys and tokens: make the file readable by you alone (chmod 600 {path}).")
        entries = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, UnicodeDecodeError):
        entries = None
    if not isinstance(entries, dict) or not all(isinstance(e, dict) for e in entries.values()):
        raise Die(f"Authentications '{path}' must be a JSON object of entries keyed by name.")
    return entries


def names(env: dict, types) -> list[str]:
    """The names of the entries of these types, for a setting to offer."""
    types = [types] if isinstance(types, str) else list(types)
    return sorted(n for n, e in load(env).items() if e.get("type") in types)


def entry(env: dict, name: str, kind: str, entries: dict | None = None) -> dict:
    """The entry `name`, which must be a complete `kind`."""
    path = auth_file(env)
    entries = load(env) if entries is None else entries
    found = entries.get(name)
    if found is None:
        raise Die(f"No authentication '{name}' in {path} (it has: {', '.join(sorted(entries)) or 'none'}).")
    if found.get("type") != kind:
        raise Die(f"Authentication '{name}' in {path} is a {found.get('type')}, not a {kind}.")
    missing = [f for f in TYPES.get(kind, ((), ()))[0] if found.get(f) in (None, "")]
    if missing:
        raise Die(f"Authentication '{name}' in {path} lacks {', '.join(missing)}.")
    return found


def apply_auth(env: dict, owners) -> list[str]:
    """For each (owner, settings) — the enabled plugins and the agent — fills, in place, the
    variables each of its "auth" settings with `fills` names an entry for. The names used."""
    used, entries = [], None
    for owner, settings in owners:
        for spec in settings:
            if spec.get("type") != "auth" or not spec.get("fills") or not env.get(spec.get("env") or ""):
                continue
            name = env[spec["env"]]
            entries = load(env) if entries is None else entries
            try:
                found = entry(env, name, spec["auth"], entries)
            except Die as e:
                raise Die(f"{owner}: {spec['env']}={name}: {e}") from None
            for key, var in spec["fills"].items():
                if found.get(key) not in (None, ""):
                    value = tostring(found[key])
                    env[var] = os.path.expanduser(value) if key.endswith("File") else value
            used.append(name)
    return used
