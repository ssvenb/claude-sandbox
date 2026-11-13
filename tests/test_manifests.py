"""The plugin and agent manifests, and the invariants they must keep."""
import json
import re
import subprocess
import sys

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


TYPES = {"boolean", "string", "path", "text", "integer", "enum", "list", "map", "object", "json"}
# Who declares settings: the kernel, each agent, each plugin.
OWNERS = ([("kernel", REPO / "src/kernel.json")] + [(f"agents/{a}", REPO / "agents" / a / "agent.json") for a in AGENTS]
          + [(f"plugins/{p}", REPO / "plugins" / p / "plugin.json") for p in PLUGINS])
# Where the settings files are: set in .env.example or the shell only, never in the config file.
NOT_IN_CONFIG = {"PROJECT_CONFIG_FILE", "PROJECT_ENV_FILE"}


def check_spec(spec, where, top=False):
    assert spec["type"] in TYPES, where
    assert isinstance(spec.get("label", ""), str) and isinstance(spec.get("description", ""), str), where
    if top:
        assert ("env" in spec) != ("key" in spec), f"{where}: exactly one of env / key"
    if spec["type"] == "enum":
        assert spec["choices"] and spec.get("default", spec["choices"][0]) in spec["choices"], where
    if spec["type"] == "list":
        check_spec(spec.get("items", {"type": "string"}), where + "[]")
    if spec["type"] == "object":
        keys = [f["key"] for f in spec["fields"]]
        assert len(keys) == len(set(keys)), where
        for f in spec["fields"]:
            check_spec(f, f"{where}.{f['key']}")
            assert set(f.get("when", {})) <= set(keys), f"{where}.{f['key']}: when names a sibling"


@pytest.mark.parametrize("owner,path", OWNERS, ids=[o for o, _ in OWNERS])
def test_declared_settings_are_well_formed(owner, path):
    """What the web UI's settings form is drawn from (see README, "Declaring settings")."""
    settings = json.loads(path.read_text()).get("settings", [])
    for spec in settings:
        check_spec(spec, f"{owner}:{spec.get('env') or spec.get('key')}", top=True)
        if "env" in spec:
            assert spec["env"] in EXAMPLE_KEYS, f"{spec['env']}: run.sh refuses names .env.example lacks"
        else:
            assert owner.startswith("plugins/"), f"{owner}: only a plugin has a section of its own"
    names = [s.get("env") or s.get("key") for s in settings]
    assert len(names) == len(set(names)), owner


def test_every_sandbox_variable_is_declared_by_exactly_one_owner():
    """.env.example and the declarations list the same names, so the form offers every one."""
    declared = [s["env"] for _, path in OWNERS for s in json.loads(path.read_text()).get("settings", []) if "env" in s]
    assert len(declared) == len(set(declared)), "declared twice"
    assert set(declared) == {k for k in EXAMPLE_KEYS if not k.startswith("ENABLE_")} - NOT_IN_CONFIG


def test_the_kernel_offers_every_agent():
    agent = next(s for s in json.loads((REPO / "src/kernel.json").read_text())["settings"] if s.get("env") == "AGENT")
    assert sorted(agent["choices"]) == AGENTS


def test_the_example_config_passes_the_declared_types():
    sys.path.insert(0, str(REPO / "web"))
    import server
    server.check_config(json.loads((REPO / ".claude-sandbox.example.json").read_text()))


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
