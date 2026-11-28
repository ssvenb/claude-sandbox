"""The plugin and agent manifests, and the invariants they must keep."""
import json
import re
import subprocess
import sys

import pytest

from conftest import REPO

PLUGINS = sorted(p.parent.name for p in REPO.glob("plugins/*/plugin.json"))
AGENTS = sorted(p.parent.name for p in REPO.glob("agents/*/agent.json"))


def manifest(name: str) -> dict:
    return json.loads((REPO / "plugins" / name / "plugin.json").read_text())


def test_every_plugin_and_agent_directory_has_a_manifest():
    assert sorted(p.name for p in (REPO / "plugins").iterdir() if p.is_dir()) == PLUGINS
    assert sorted(p.name for p in (REPO / "agents").iterdir() if p.is_dir()) == AGENTS


@pytest.mark.parametrize("name", PLUGINS)
def test_plugin_manifest_is_well_formed(name):
    m = manifest(name)
    assert m["name"] == name
    assert isinstance(m.get("priority", 50), int)
    assert isinstance(m["defaultEnabled"], bool)
    for key in ("provides", "requires", "conflicts", "requiredEnv"):
        assert isinstance(m.get(key, []), list), key
    assert "secrets" not in m  # gone: nothing in the container is kept from the agent
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
def test_every_required_variable_is_a_declared_setting(name):
    """A plugin requires a setting of its own, so the project's file (and the form) can set it."""
    declared = {s.get("env") for s in manifest(name).get("settings", [])}
    assert set(manifest(name).get("requiredEnv", [])) <= declared


SETTING_VARS = {s["env"] for path in [*REPO.glob("plugins/*/plugin.json"), *REPO.glob("agents/*/agent.json"),
                                       REPO / "src/orchestrator/kernel.json"]
                for s in json.loads(path.read_text()).get("settings", []) if "env" in s}
TYPES = {"boolean", "string", "path", "text", "integer", "enum", "list", "map", "object", "json", "auth"}
# Who declares settings: the kernel, each agent, each plugin.
OWNERS = ([("kernel", REPO / "src/orchestrator/kernel.json")] + [(f"agents/{a}", REPO / "agents" / a / "agent.json") for a in AGENTS]
          + [(f"plugins/{p}", REPO / "plugins" / p / "plugin.json") for p in PLUGINS])


def check_spec(spec, where, top=False):
    assert spec["type"] in TYPES, where
    assert isinstance(spec.get("label", ""), str) and isinstance(spec.get("description", ""), str), where
    if top:
        assert "key" in spec, f"{where}: where it sits in the project's file"
    if spec["type"] == "auth":
        from orchestrator.auth import TYPES as AUTH_TYPES
        kinds = [spec["auth"]] if isinstance(spec["auth"], str) else spec["auth"]
        assert kinds and set(kinds) <= set(AUTH_TYPES), where
        if "fills" in spec:  # what an entry of that type holds, into variables no project may set
            assert isinstance(spec["auth"], str) and "env" in spec, where
            held = set(sum(AUTH_TYPES[spec["auth"]], ()))
            assert set(spec["fills"]) <= held, f"{where}: fills what a {spec['auth']} does not hold"
            assert not set(spec["fills"].values()) & SETTING_VARS, f"{where}: a filled variable must not be a setting"
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
        check_spec(spec, f"{owner}:{spec.get('key')}", top=True)
    keys = [s["key"] for s in settings]
    assert len(keys) == len(set(keys)), owner
    if owner == "kernel":  # they sit at the top of the file, beside these
        assert not set(keys) & {"repo", "agents", "plugins"}


def test_every_settings_variable_is_declared_by_exactly_one_owner():
    """The stages read a setting from its variable, so two owners must not share one."""
    declared = [s["env"] for _, path in OWNERS for s in json.loads(path.read_text()).get("settings", []) if "env" in s]
    assert len(declared) == len(set(declared)), "declared twice"


def test_the_kernel_offers_every_agent():
    agent = next(s for s in json.loads((REPO / "src/orchestrator/kernel.json").read_text())["settings"] if s.get("key") == "agent")
    assert sorted(agent["choices"]) == AGENTS


def test_the_example_config_passes_the_declared_types(tmp_path, monkeypatch):
    """With the authentications its routes name configured: a name auth.json lacks is refused."""
    file = tmp_path / "auth.json"
    file.write_text(json.dumps({"cribl": {"type": "oauth2-client"}, "azure-openai": {"type": "api-key"},
                                "gcs-reader": {"type": "gcp-service-account"}}))
    file.chmod(0o600)
    monkeypatch.setenv("SANDBOX_AUTH_FILE", str(file))
    sys.path.insert(0, str(REPO / "src/server"))
    import server
    example = json.loads((REPO / ".claude-sandbox.example.json").read_text())
    server.check_config(example)
    file.write_text(json.dumps({"cribl": {"type": "api-key"}}))
    with pytest.raises(ValueError, match=r"routes\[1\]\.auth\.credential: no api-key or oauth2-client or gcp-service-account called 'azure-openai' in .* \(there: cribl\)"):
        server.check_config(example)


def test_settings_fragments_are_json_objects():
    for path in REPO.glob("plugins/*/settings.json"):
        assert isinstance(json.loads(path.read_text()), dict), path


def test_scripts_run_directly_are_executable_in_git():
    """run.sh and the Dockerfile execute these by path, so a lost exec bit breaks a run."""
    listed = subprocess.run(["git", "ls-files", "-s"], cwd=REPO, capture_output=True, text=True,
                            check=True).stdout
    modes = {line.split("\t")[1]: line.split()[0] for line in listed.splitlines()}
    direct = ["run.sh", "install.sh", "src/server/serve.sh", "src/server/main.py", "src/server/holder.py", "src/boot/agent-setup.sh"] + [
        path for path in modes if re.match(r"plugins/[^/]+/(host|root|bin)/", path)]
    for path in direct:  # a symlink runs its target, which is listed too
        assert modes[path] in ("100755", "120000"), path


def test_example_project_config_is_accepted(sb):
    """.claude-sandbox.example.json is documentation, so it must at least load and validate."""
    sb.staged("", PROJECT_CONFIG_FILE=REPO / ".claude-sandbox.example.json").ok()
