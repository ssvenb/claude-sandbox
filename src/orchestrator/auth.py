"""Named authentications: the identities sandboxes may act as (a GitHub App, a Google Cloud
service account), kept in one file on YOUR machine, outside every project:

    ~/.config/claude-sandbox/auth.json        (SANDBOX_AUTH_FILE points somewhere else)
    {
      "coder":    {"type": "github-app", "appId": "123456", "privateKeyFile": "~/keys/coder.pem"},
      "reviewer": {"type": "github-app", "appId": "234567", "privateKeyFile": "~/keys/reviewer.pem"},
      "ci-data":  {"type": "gcp-service-account", "serviceAccount": "sandbox@my-project.iam.gserviceaccount.com"},
      "openai":   {"type": "api-key", "key": "sk-…"}
    }

A plugin that authenticates declares, in its manifest, which setting names the entry it uses and
which of its own settings each field of the entry fills:

    "auth": {"type": "github-app", "env": "GH_AUTH",
             "fields": {"appId": "GH_APP_ID", "privateKeyFile": "GH_PRIVATE_KEY_FILE"}}

With GH_AUTH=reviewer the plugin runs exactly as if those settings had been made one by one, so
its stages need not know. What a key file is exchanged for is still minted on the host
(src/services/credentials).

An `api-key` entry (a model provider's API key) is the one that holds a secret itself, so it is
never turned into settings: upstream-proxy reads it in its own host process, for a route whose
auth.credential names it (run.sh hands every stage the file's path as SANDBOX_AUTH_FILE), and
refuses the file unless only you can read it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import Die
from .config import tostring


def auth_file(env: dict) -> Path:
    return Path(env.get("SANDBOX_AUTH_FILE")
                or Path(env.get("XDG_CONFIG_HOME") or Path(env.get("HOME") or Path.home()) / ".config")
                / "claude-sandbox/auth.json")


def apply_auth(env: dict, plugins: list) -> list[str]:
    """Fills, in place, the settings of each plugin that names an authentication. The names used."""
    used, entries = [], None
    for p in plugins:
        name = env.get((p.auth or {}).get("env") or "")
        if not name:
            continue
        path = auth_file(env)
        if entries is None:
            try:
                entries = json.loads(path.read_text())
            except FileNotFoundError:
                entries = {}
            except (OSError, ValueError, UnicodeDecodeError):
                entries = None
            if not isinstance(entries, dict):
                raise Die(f"Authentications '{path}' must be a JSON object keyed by name.")
        entry = entries.get(name)
        if not isinstance(entry, dict):
            raise Die(f"Plugin '{p.name}': {p.auth['env']} names the authentication '{name}', which {path} "
                      f"does not have (it has: {', '.join(sorted(entries)) or 'none'}).")
        if entry.get("type") != p.auth.get("type"):
            raise Die(f"Plugin '{p.name}' takes a {p.auth.get('type')} authentication; "
                      f"'{name}' in {path} is a {entry.get('type')}.")
        for key, var in (p.auth.get("fields") or {}).items():
            if entry.get(key) not in (None, ""):
                value = tostring(entry[key])
                # A key file is named from your home, not from whichever project runs.
                env[var] = os.path.expanduser(value) if key.endswith("File") else value
        used.append(name)
    return used
