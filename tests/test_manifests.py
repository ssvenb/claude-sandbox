"""The plugin and agent manifests, and the invariants they must keep."""
import json
import re
import subprocess

import pytest

from conftest import REPO

PLUGINS = sorted(p.parent.name for p in REPO.glob("plugins/*/plugin.json"))
AGENTS = sorted(p.parent.name for p in REPO.glob("agents/*/agent.json"))
EXAMPLE_KEYS = set(re.findall(r"^#?\s*([A-Z_][A-Z0-9_]*)=", (REPO / ".env.example").read_text(), re.M))


def manifest(name: str) -> dict:
    return json.loads((REPO / "plugins" / name / "plugin.json").read_text())


def flag(name: str) -> str:
    return "ENABLE_" + name.upper().replace("-", "_")


def test_every_plugin_and_agent_directory_has_a_manifest():
    assert sorted(p.name for p in (REPO / "plugins").iterdir() if p.is_dir()) == PLUGINS
    assert sorted(p.name for p in (REPO / "agents").iterdir() if p.is_dir()) == AGENTS


@pytest.mark.parametrize("name", PLUGINS)
def test_plugin_manifest_is_well_formed(name):
    m = manifest(name)
    assert m["name"] == name
    assert isinstance(m.get("priority", 50), int)
    assert isinstance(m["defaultEnabled"], bool)
    for key in ("provides", "requires", "conflicts", "requiredEnv", "secrets"):
        assert isinstance(m.get(key, []), list), key
    assert m.get("requiredAgent", AGENTS[0]) in AGENTS
    assert set(m.get("conflicts", [])) <= set(PLUGINS)


@pytest.mark.parametrize("name", AGENTS)
def test_agent_manifest_is_well_formed(name):
    m = json.loads((REPO / "agents" / name / "agent.json").read_text())
    assert m["name"] == name
    assert m["managedSettings"].startswith("/")
    assert m["git"]["branchPrefix"] and m["git"]["userName"]
    assert (REPO / "agents" / name / "launch.sh").is_file()


@pytest.mark.parametrize("name", PLUGINS)
def test_every_required_capability_has_a_provider(name):
    provided = {cap for p in PLUGINS for cap in manifest(p).get("provides", [])}
    assert set(manifest(name).get("requires", [])) <= provided


@pytest.mark.parametrize("name", PLUGINS)
def test_env_example_documents_the_plugin_flag_with_its_default(name):
    """.env.example is the allowlist of sandbox-owned names, so every flag must be in it."""
    text = (REPO / ".env.example").read_text()
    found = re.search(rf"^#?{flag(name)}=(\S*)", text, re.M)
    assert found, f"{flag(name)} missing from .env.example"
    assert found[1] == ("1" if manifest(name)["defaultEnabled"] else "0")


@pytest.mark.parametrize("var", sorted({v for p in PLUGINS for v in manifest(p).get("requiredEnv", [])}))
def test_env_example_documents_every_required_variable(var):
    assert var in EXAMPLE_KEYS


def test_settings_fragments_are_json_objects():
    for path in REPO.glob("plugins/*/settings.json"):
        assert isinstance(json.loads(path.read_text()), dict), path


def test_scripts_run_directly_are_executable_in_git():
    """run.sh and the Dockerfile execute these by path, so a lost exec bit breaks a run."""
    listed = subprocess.run(["git", "ls-files", "-s"], cwd=REPO, capture_output=True, text=True,
                            check=True).stdout
    modes = {line.split("\t")[1]: line.split()[0] for line in listed.splitlines()}
    direct = ["run.sh", "src/agent-setup.sh"] + [
        path for path in modes if re.match(r"plugins/[^/]+/(host|root|bin)/", path)]
    for path in direct:
        assert modes[path] == "100755", path


def test_example_project_config_is_accepted(sb):
    """.claude-sandbox.example.json is documentation, so it must at least load and validate."""
    run = sb.bash("project_config_load\nproject_env_load\nproject_settings_apply",
                  PROJECT_CONFIG_FILE=REPO / ".claude-sandbox.example.json")
    run.ok()
