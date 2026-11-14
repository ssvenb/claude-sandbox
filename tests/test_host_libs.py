"""The host side under src/host (Python: config, precedence, plugins, agents) and the bash
libraries the plugins' stages are sourced with, src/lib/host-*.sh (helpers, credentials)."""
import json
import os
import time

import pytest

from conftest import REPO, host
from host import agents, config, plugins


def scan(sb, text, commented=False, shell="python"):
    path = sb.tmp / "scanned.env"
    path.write_bytes(text.encode())
    if shell == "python":
        return config.scan_env(path, commented)
    run = sb.bash(f'declare -A OUT=()\nenv_scan_into OUT "{path}" {"commented" if commented else ""}\n'
                  'for k in "${!OUT[@]}"; do printf "%s=%s\\0" "$k" "${OUT[$k]}"; done').ok()
    return dict(item.split("=", 1) for item in run.out.split("\0")[:-1])


# --- .env files: src/host/config.py and host-project-env.sh read them alike ---------------

BOTH = pytest.mark.parametrize("shell", ["python", "bash"])


@BOTH
def test_env_scan_parses_without_executing(sb, shell):
    text = "\n".join([
        "# comment", "", "export A=1", 'B = "two words"', "C='single'", "D=x=y", "   E=  padded  ",
        "F=$(touch pwned)", "1BAD=no", "some prose with = in it", "G=crlf\r", "A=2", "H=\"", "I=''",
        "\tJ=\ttabbed\t", "exportK=glued", "L=#not a comment",
    ])
    assert scan(sb, text, shell=shell) == {
        "A": "2", "B": "two words", "C": "single", "D": "x=y", "E": "padded", "F": "$(touch pwned)",
        "G": "crlf", "H": '"', "I": "", "J": "tabbed", "K": "glued", "L": "#not a comment"}
    assert not (REPO / "pwned").exists()


@BOTH
def test_env_scan_commented_mode_reads_documented_defaults(sb, shell):
    assert scan(sb, "#BASE_BRANCH=main\n# prose here\nAGENT=claude\n", True, shell) == {
        "BASE_BRANCH": "main", "AGENT": "claude"}
    assert scan(sb, "#BASE_BRANCH=main\n", shell=shell) == {}


def test_both_parsers_agree_on_the_sandboxs_own_example(sb):
    text = (REPO / ".env.example").read_text()
    assert scan(sb, text, True) == scan(sb, text, True, "bash")


def test_project_env_reads_one_key_from_the_repos_env(sb):
    sb.dotenv("BRANCH_PREFIX=feature\n")
    run = sb.bash('project_env_load\necho "[$(project_env BRANCH_PREFIX)] [$(project_env NOPE dflt)]"').ok()
    assert run.out == "[feature] [dflt]\n"


def test_project_env_file_can_be_switched_off(sb):
    sb.dotenv("BRANCH_PREFIX=feature\n")
    run = sb.bash('project_env_load\necho "[$(project_env BRANCH_PREFIX)]"', PROJECT_ENV_FILE="/dev/null")
    assert run.ok().out == "[]\n"


# --- .claude-sandbox.json -----------------------------------------------------------------

@pytest.mark.parametrize("content, message", [
    ("[]", "must be a JSON object"),
    ("not json", "must be a JSON object"),
    ('{"plugins": []}', ".plugins must be an object"),
    ('{"env": {"A": {"b": 1}}}', ".env must be an object of scalar values"),
    ('{"env": {"A": [1]}}', ".env must be an object of scalar values"),
])
def test_malformed_project_config_fails(sb, content, message):
    (sb.cwd / ".claude-sandbox.json").write_text(content)
    sb.staged("").dies(message)


def test_plugin_settings_are_read_from_the_plugins_own_section(sb):
    sb.config({"plugins": {"demo": {"name": "x", "off": False, "list": [1, 2], "obj": {"a": 1}}}})
    run = sb.staged("PLUGIN_NAME=demo\n"
                    "for f in .name .off .missing; do echo \"[$(plugin_config $f dflt)]\"; done\n"
                    "plugin_config_json .list; echo; plugin_config_json .obj; echo; plugin_config_json .missing '[]'").ok()
    assert run.out.splitlines() == ["[x]", "[false]", "[dflt]", "[1,2]", '{"a":1}', "[]"]


def test_plugin_settings_without_a_config_file_are_the_defaults(sb):
    run = sb.staged('PLUGIN_NAME=demo\necho "[$(plugin_config .x d)] $(plugin_config_json .y)"')
    assert run.ok().out == "[d] null\n"


def test_plugin_config_outside_a_plugin_stage_is_an_error(sb):
    sb.config({})
    sb.staged("plugin_config .x").dies("outside a plugin stage")


def test_project_config_file_location_can_be_overridden(sb):
    other = sb.tmp / "elsewhere.json"
    other.write_text(json.dumps({"plugins": {"demo": {"v": "here"}}}))
    run = sb.staged("project_plugin_setting demo .v", PROJECT_CONFIG_FILE=other)
    assert run.ok().out.endswith("here")


# --- settings: precedence -----------------------------------------------------------------

def test_each_layer_overrides_the_one_below(sb):
    show = 'echo "effort=$CLAUDE_EFFORT"'
    assert sb.staged(show, CLAUDE_EFFORT="low").ok().out.endswith("effort=low\n")
    sb.dotenv("CLAUDE_EFFORT=high\n")
    assert sb.staged(show, CLAUDE_EFFORT="low").ok().out.endswith("effort=high\n")
    sb.config({"env": {"CLAUDE_EFFORT": "max"}})
    assert sb.staged(show, CLAUDE_EFFORT="low").ok().out.endswith("effort=max\n")


def test_only_sandbox_owned_names_are_lifted_from_the_repos_env(sb):
    sb.dotenv("SECRET_API_KEY=hunter2\nENABLE_ANYTHING=0\nGH_APP_ID=99\n")
    run = sb.staged('echo "secret=${SECRET_API_KEY-unset} flag=$ENABLE_ANYTHING app=$GH_APP_ID"\n'
                    'env | grep -c hunter2 || true').ok()
    assert "secret=unset flag=0 app=99" in run.out
    assert run.out.endswith("0\n")
    env = sb._env({})
    assert config.apply_settings(env, config.load_project(env)) == ["ENABLE_ANYTHING", "GH_APP_ID"]


def test_an_unknown_name_in_the_config_env_block_is_a_typo(sb):
    sb.config({"env": {"CLAUDE_EFORT": "high"}})
    sb.staged("").dies(".env.CLAUDE_EFORT is not a sandbox setting")


def test_config_env_scalars_become_strings(sb):
    sb.config({"env": {"ENABLE_KVM": 0, "ENABLE_HERDR": True, "AGENT_VERSION": 1.5, "PORTS": 3000.0}})
    run = sb.staged('echo "$ENABLE_KVM $ENABLE_HERDR $AGENT_VERSION $PORTS"').ok()
    assert run.out.endswith("0 true 1.5 3000\n")


# --- plugins: discovery, enablement, validation (src/host/plugins.py) ---------------------

@pytest.fixture
def fake_plugins(sb):
    root = sb.tmp / "plugins"

    def make(name, host_sh=None, **manifest):
        (root / name).mkdir(parents=True)
        (root / name / "plugin.json").write_text(json.dumps({"name": name, **manifest}))
        if host_sh:
            (root / name / "host.sh").write_text(host_sh)
    make.root = root
    return make


def resolve(sb, root, validate=False, **env):
    """The names of the plugins that would run, or the refusal's message."""
    env = sb._env(env)
    try:
        project = config.load_project(env)
        config.apply_settings(env, project)
        found = plugins.discover(root)
        enabled = plugins.resolve(found, env, project, env.get("AGENT") or "claude")
        if validate:
            plugins.validate(enabled, found, env)
    except host.Die as e:
        return f"❌ {e}"
    return " ".join(p.name for p in enabled)


def test_flag_names():
    assert plugins.flag_name("github-auth") == "ENABLE_GITHUB_AUTH"
    assert plugins.flag_name("a-b-c") == "ENABLE_A_B_C"


def test_plugins_run_in_priority_then_name_order(sb, fake_plugins):
    fake_plugins("zeta", priority=10, defaultEnabled=True)
    fake_plugins("beta", priority=20, defaultEnabled=True)
    fake_plugins("alpha", priority=10, defaultEnabled=True)
    fake_plugins("mid", defaultEnabled=True)  # no priority: 50
    assert resolve(sb, fake_plugins.root) == "alpha zeta beta mid"


def test_discovery_failures(sb, fake_plugins):
    assert resolve(sb, fake_plugins.root) == f"❌ Plugin directory not found: {fake_plugins.root}"
    fake_plugins.root.mkdir()
    assert "No plugins found" in resolve(sb, fake_plugins.root)
    (fake_plugins.root / "broken").mkdir()
    (fake_plugins.root / "broken/plugin.json").write_text("{nope")
    assert "Malformed manifest" in resolve(sb, fake_plugins.root)


def test_enablement_precedence(sb, fake_plugins):
    fake_plugins("on-by-default", defaultEnabled=True)
    fake_plugins("off-by-default", defaultEnabled=False)
    fake_plugins("unspecified")
    root = fake_plugins.root
    assert resolve(sb, root) == "on-by-default"
    flags = {"ENABLE_ON_BY_DEFAULT": "off", "ENABLE_OFF_BY_DEFAULT": "yes", "ENABLE_UNSPECIFIED": "true"}
    assert resolve(sb, root, **flags) == "off-by-default unspecified"
    sb.config({"plugins": {"unspecified": {"enabled": False}, "on-by-default": {"enabled": 1}}})
    assert resolve(sb, root, **flags) == "off-by-default on-by-default"


@pytest.mark.parametrize("config_, env, source", [
    ({}, {"ENABLE_P": "maybe"}, "ENABLE_P must be 0 or 1 (got: maybe)"),
    ({"plugins": {"p": {"enabled": "sometimes"}}}, {}, '.plugins["p"].enabled) must be 0 or 1'),
])
def test_invalid_enablement_names_its_source(sb, fake_plugins, config_, env, source):
    fake_plugins("p")
    sb.config(config_)
    assert source in resolve(sb, fake_plugins.root, **env)


def test_agent_specific_plugins_drop_out_for_other_agents(sb, fake_plugins):
    fake_plugins("claude-only", defaultEnabled=True, requiredAgent="claude")
    fake_plugins("any", defaultEnabled=True)
    assert resolve(sb, fake_plugins.root, AGENT="claude") == "any claude-only"
    assert resolve(sb, fake_plugins.root, AGENT="copilot") == "any"


def test_conflicting_plugins_cannot_run_together(sb, fake_plugins):
    fake_plugins("a", defaultEnabled=True, conflicts=["b"])
    fake_plugins("b", defaultEnabled=True)
    assert "Plugins 'a' and 'b' cannot be enabled together" in resolve(sb, fake_plugins.root, True)
    assert resolve(sb, fake_plugins.root, True, ENABLE_B=0) == "a"


def test_required_env_must_be_set(sb, fake_plugins):
    fake_plugins("needy", defaultEnabled=True, requiredEnv=["NEEDY_KEY"])
    assert "Plugin 'needy' requires NEEDY_KEY" in resolve(sb, fake_plugins.root, True)
    assert resolve(sb, fake_plugins.root, True, NEEDY_KEY="x") == "needy"


def test_required_capabilities_name_their_providers(sb, fake_plugins):
    fake_plugins("consumer", defaultEnabled=True, requires=["workspace"])
    fake_plugins("prov-a", provides=["workspace"])
    fake_plugins("prov-b", provides=["workspace", "other"])
    fake_plugins("lonely", defaultEnabled=True, requires=["nothing-provides-this"])
    assert "requires the 'workspace' capability. Enable one of: prov-a,prov-b" in resolve(
        sb, fake_plugins.root, True, ENABLE_LONELY=0)
    assert resolve(sb, fake_plugins.root, True, ENABLE_LONELY=0, ENABLE_PROV_B=1) == "consumer prov-b"
    assert "<none available>" in resolve(sb, fake_plugins.root, True, ENABLE_CONSUMER=0)


# --- host-plugins.sh: what a host.sh is sourced with ---------------------------------------

def test_pass_helpers_build_the_docker_command_line(sb, tmp_path):
    run = sb.bash(f'SET=value EMPTY=""\npass_env SET EMPTY UNSET\npass_value COMPUTED "a b"\n'
                  f'pass_arg --cap-add=NET_ADMIN --device=/dev/net/tun\npass_mount "{tmp_path}" /data ro\n'
                  f'pass_mount "{tmp_path}" /rw\npass_build_arg EXTRA "x y"').ok()
    assert run.args == ["-e", "SET=value", "-e", "COMPUTED=a b", "--cap-add=NET_ADMIN",
                        "--device=/dev/net/tun", "-v", f"{tmp_path}:/data:ro", "-v", f"{tmp_path}:/rw"]
    assert run.build_args == ["--build-arg", "EXTRA=x y"]


def test_mounting_a_missing_path_fails_naming_the_plugin(sb):
    sb.bash("PLUGIN_NAME=demo\npass_mount /no/such/path /x").dies("Plugin 'demo' wants to mount '/no/such/path'")


@pytest.mark.parametrize("ending", ["true", "die boom"])
def test_exit_hooks_all_run_in_order_however_the_run_ends(sb, ending):
    log = sb.tmp / "hooks.log"
    sb.bash(f'on_exit "echo first >>{log}"\non_exit "echo second >>{log}"\n{ending}')
    assert log.read_text() == "first\nsecond\n"


def test_host_stage_sources_each_enabled_plugin_with_its_name_and_dir(sb, fake_plugins):
    fake_plugins("one", 'pass_value SEEN_ONE "$PLUGIN_NAME:$PLUGIN_DIR"\n')
    fake_plugins("two")  # no host.sh at all
    fake_plugins("three", 'pass_value SEEN_THREE "$PLUGIN_NAME"\n')  # not enabled
    run = sb.bash('plugins_host_stage\necho "after=[${PLUGIN_NAME-unset}]"', PLUGIN_ROOT=fake_plugins.root,
                  ENABLED_PLUGINS="one two").ok()
    assert run.env == {"SEEN_ONE": f"one:{fake_plugins.root}/one"}
    assert "after=[unset]" in run.out


# --- host-credentials.sh -------------------------------------------------------------------

@pytest.mark.parametrize("args, message", [
    ("Bad_Name 60 mint", "must be lowercase letters"),
    (".hidden 60 mint", "must be lowercase letters"),
    ("tok 59 mint", "at least 60 seconds"),
    ("tok soon mint", "at least 60 seconds"),
    ("tok 60 not_a_function", "is not a shell function"),
])
def test_register_credential_validates(sb, args, message):
    sb.bash(f"mint() {{ echo t; }}\nPLUGIN_NAME=demo\nregister_credential {args}").dies(message)


def test_minting_replaces_the_file_and_a_failure_keeps_the_old_one(sb):
    d = sb.tmp / "creds"
    d.mkdir()
    run = sb.bash(f'CREDENTIALS_DIR="{d}"\n'
                  'good() { echo fresh; }\nbad() { echo partial; return 1; }\nempty() { :; }\n'
                  'credential_mint tok good\n'
                  'credential_mint tok bad && echo "bad succeeded"\n'
                  'credential_mint tok empty && echo "empty succeeded"\n'
                  'cat "$CREDENTIALS_DIR/tok"; ls -A "$CREDENTIALS_DIR"').ok()
    assert run.out == "fresh\ntok\n"


def test_no_credentials_means_no_mount(sb):
    assert sb.bash("credentials_start").ok().args == []


def test_credentials_are_minted_and_mounted_read_only(sb):
    run = sb.bash('mint() { echo "token-1"; }\nregister_credential tok 3600 mint\ncredentials_start\n'
                  'stat -c "%a" "$CREDENTIALS_ROOT" "$CREDENTIALS_DIR" "$CREDENTIALS_DIR/tok"\n'
                  'echo "root=$CREDENTIALS_ROOT"').ok()
    root = run.out.split("root=")[1].strip()
    [mount] = run.mounts
    assert mount == f"{root}/credentials:/run/credentials:ro"
    assert "700\n755\n644\n" in run.out
    assert "🔑 Credentials: tok" in run.out
    assert not os.path.exists(root), "the credentials dir outlived run.sh"


def test_a_credential_that_cannot_be_minted_fails_the_run(sb):
    sb.bash('mint() { echo "no key here" >&2; return 1; }\nregister_credential tok 60 mint\n'
            'credentials_start').dies("Could not mint credential 'tok':\nno key here")


def test_refresher_follows_the_wall_clock(sb):
    """sleep is stubbed to return at once and the clock to jump 61s per reading — a run that keeps
    getting suspended — so each round of the refresher finds the credential due."""
    clock = sb.tmp / "clock"
    clock.write_text(str(int(time.time())))
    sb.stub("sleep", "/bin/sleep 0.05\n")
    sb.stub("date", f'if [ "$1" = +%s ]; then n=$(( $(cat {clock}) + 61 )); echo $n >{clock}; echo $n; '
                    'else exec /bin/date "$@"; fi\n')
    counter = sb.tmp / "count"
    counter.write_text("0")
    run = sb.bash(f'mint() {{ n=$(( $(cat {counter}) + 1 )); echo $n >{counter}; '
                  '[ "$n" -ne 3 ] || return 1; [ "$n" -le 5 ] || n=5; echo "token-$n"; }\n'
                  'register_credential tok 60 mint\ncredentials_start\n'
                  'for _ in $(seq 100); do [ "$(cat "$CREDENTIALS_DIR/tok")" = token-5 ] && break; /bin/sleep 0.05; done\n'
                  'cat "$CREDENTIALS_DIR/tok"; cat "$CREDENTIALS_LOG"').ok()
    lines = run.out.splitlines()
    assert "token-5" in lines
    log = "\n".join(lines)
    assert "refreshed tok" in log
    assert "could not refresh tok; retrying in a minute" in log


# --- agents (src/host/agents.py) ----------------------------------------------------------

def agent(sb, **env):
    try:
        return agents.resolve_agent(sb._env(env))
    except host.Die as e:
        return f"❌ {e}"


def test_agent_defaults_to_claude(sb):
    found = agent(sb, AGENT=None)
    assert (found.name, found.dir) == ("claude", REPO / "agents/claude")


@pytest.mark.parametrize("name, message", [
    ("Bad_Name", "Invalid AGENT 'Bad_Name'"),
    ("nope", "Unknown agent 'nope'. Available: claude copilot"),
])
def test_agent_must_exist(sb, name, message):
    assert message in agent(sb, AGENT=name)


def test_malformed_agent_manifest(sb):
    (sb.tmp / "agents/broken").mkdir(parents=True)
    (sb.tmp / "agents/broken/agent.json").write_text("{")
    assert "Malformed manifest" in agent(sb, AGENT="broken", AGENT_ROOT=sb.tmp / "agents")


@pytest.fixture
def registry(monkeypatch):
    """The npm registry, answering `version` (None: unreachable); the packages asked about."""
    asked = []

    def answer(version):
        def latest(package):
            asked.append(package)
            return version or ""
        monkeypatch.setattr(agents, "latest_version", latest)
    answer.asked = asked
    return answer


def test_a_pinned_version_is_kept(sb, registry, capsys):
    registry("9.9.9")
    assert agents.resolve_version(agent(sb), {"AGENT_VERSION": "1.2.3"}) == "1.2.3"
    assert registry.asked == [] and "@anthropic-ai/claude-code@1.2.3 (pinned)" in capsys.readouterr().out


@pytest.mark.parametrize("name, package", [("claude", "@anthropic-ai/claude-code"), ("copilot", "@github/copilot")])
def test_latest_version_comes_from_the_npm_registry(sb, registry, capsys, name, package):
    registry("9.9.9")
    assert agents.resolve_version(agent(sb, AGENT=name), {}) == "9.9.9"
    assert registry.asked == [package] and "(latest)" in capsys.readouterr().out


def test_an_unreachable_registry_keeps_the_image_version(sb, registry, capsys):
    registry(None)
    assert agents.resolve_version(agent(sb), {}) == ""
    assert "Could not reach the npm registry" in capsys.readouterr().out


def test_agent_without_npm_package_skips_version_lookup(sb, registry, capsys):
    (sb.tmp / "agents/plain").mkdir(parents=True)
    (sb.tmp / "agents/plain/agent.json").write_text("{}")
    registry("9.9.9")
    assert agents.resolve_version(agent(sb, AGENT="plain", AGENT_ROOT=sb.tmp / "agents"), {}) == ""
    assert registry.asked == [] and capsys.readouterr().out == ""
    assert sb.bash("agent_host_stage", AGENT="plain", AGENT_ROOT=sb.tmp / "agents").ok().out == ""
