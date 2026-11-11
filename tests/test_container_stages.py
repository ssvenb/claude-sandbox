"""Container-side stages that need neither root nor /workspace, sourced by `sh` as in the image.

The rest — entrypoint.sh, agent-setup.sh, the root stages, git-workspace and github-auth's
agent stages — only make sense inside the real image; tests/e2e boots it.
"""
import json
import stat

import pytest

from conftest import REPO


def stub_agent(sb):
    """An agent binary that records its argv, NUL-separated."""
    out = sb.tmp / "argv"
    sb.stub("fake-agent", f'printf "%s\\0" "$@" >"{out}"\n')
    return lambda: out.read_text().split("\0")[:-1]


# --- src/lib/plugins.sh, src/lib/agents.sh -------------------------------------------------

def test_stages_run_in_the_order_the_host_resolved(sb):
    root = sb.tmp / "plugins"
    for name in ("a", "b", "c"):
        (root / name).mkdir(parents=True)
    for name in ("a", "b"):
        (root / name / "agent-init.sh").write_text(
            f'echo "$PLUGIN_NAME:$PLUGIN_DIR" >>"$AGENT_PROMPT_FILE"\nexport FROM_{name}=1\n')
    run = sb.sh('plugin_run_stage agent-init\necho "a=$FROM_a b=$FROM_b after=${PLUGIN_NAME-unset}"',
                PLUGIN_ROOT=root, ENABLED_PLUGINS="b ghost c a").ok()
    assert run.prompt == f"b:{root}/b\na:{root}/a\n"
    assert run.out == "a=1 b=1 after=unset\n"   # sourced: exports reach the rest of the boot
    assert "Unknown plugin 'ghost'" in run.err


def test_settings_fragments_and_secrets_of_enabled_plugins(sb):
    run = sb.sh("plugin_settings_files\necho ---\nplugin_secret_vars",
                ENABLED_PLUGINS="github-auth branch-guard netbird gcp-auth").ok()
    assert run.out == f"{REPO}/plugins/branch-guard/settings.json\n---\nNB_SETUP_KEY\n"
    assert sb.sh("plugin_settings_files; plugin_secret_vars", ENABLED_PLUGINS="").ok().out == ""


def test_container_agent_framework(sb):
    run = sb.sh('echo "$AGENT $AGENT_DIR"; agent_meta .managedSettings; agent_run_stage no-such-stage; echo ok',
                AGENT=None).ok()
    assert run.out == f"claude {REPO}/agents/claude\n/etc/claude-code/managed-settings.json\nok\n"
    sb.sh("true", AGENT="nope").dies("Unknown agent 'nope'")


# --- agents --------------------------------------------------------------------------------

def test_claude_config_is_seeded_for_an_unattended_boot(sb):
    run = sb.sh('agent_run_stage agent-init\necho "$DISABLE_AUTOUPDATER"').ok()
    assert run.out == "1\n"
    cfg = json.loads((sb.home / ".claude.json").read_text())
    assert cfg["hasCompletedOnboarding"] and cfg["bypassPermissionsModeAccepted"]
    assert cfg["skipDangerousModePermissionPrompt"] and cfg["theme"] == "dark"
    assert cfg["projects"]["/workspace"]["hasTrustDialogAccepted"]
    playwright = cfg["mcpServers"]["playwright"]
    assert playwright["command"] == "playwright-mcp"
    assert {"--headless", "--isolated", "--no-sandbox", "/usr/bin/chromium"} <= set(playwright["args"])


def test_claude_seeding_keeps_an_existing_config(sb):
    (sb.home / ".claude.json").write_text(json.dumps(
        {"theme": "light", "oauthAccount": {"id": 1}, "projects": {"/other": {"x": 1}}}))
    sb.sh("agent_run_stage agent-init").ok()
    cfg = json.loads((sb.home / ".claude.json").read_text())
    assert cfg["theme"] == "light" and cfg["oauthAccount"] == {"id": 1}
    assert cfg["projects"]["/other"] == {"x": 1} and cfg["projects"]["/workspace"]["hasTrustDialogAccepted"]


@pytest.mark.parametrize("prompt, effort, tail", [
    ("", None, ["--effort", "medium"]),
    ("Line one.\nLine two.", "max", ["--effort", "max", "--append-system-prompt", "Line one.\nLine two."]),
])
def test_claude_launch(sb, prompt, effort, tail):
    argv = stub_agent(sb)
    sb.sh("agent_run_stage launch", AGENT_LAUNCH_CMD="fake-agent --wrapped", AGENT_PROMPT=prompt,
          CLAUDE_EFFORT=effort).ok()
    assert argv() == ["--wrapped", "--dangerously-skip-permissions", *tail]


def test_copilot_is_prepared_for_an_unattended_boot(sb):
    run = sb.sh('agent_run_stage agent-init\necho "$COPILOT_AUTO_UPDATE $COPILOT_HOME $COPILOT_ALLOW_ALL"',
                AGENT="copilot").ok()
    assert run.out == f"false {sb.home}/.copilot true\n"
    assert (sb.home / ".copilot").is_dir()


@pytest.mark.parametrize("prompt", ["", "Context."])
def test_copilot_launch(sb, prompt):
    argv = stub_agent(sb)
    sb.sh("agent_run_stage launch", AGENT="copilot", AGENT_LAUNCH_CMD="fake-agent", AGENT_PROMPT=prompt).ok()
    if not prompt:
        assert argv() == ["--allow-all"]
    else:
        flag, message = argv()[1:]
        assert flag == "-i" and message.startswith("Context.\n")
        assert "do not take any action on it" in message


# --- plugin briefings and agent-user setup -------------------------------------------------

def stage(sb, plugin, **env):
    return sb.sh(f". {REPO}/plugins/{plugin}/agent-init.sh", **env).ok()


def test_cwd_workspace_names_the_masked_files(sb):
    assert stage(sb, "cwd-workspace").prompt == ""
    prompt = stage(sb, "cwd-workspace", CWD_WORKSPACE_HIDDEN="/workspace/.env /workspace/k.json").prompt
    assert "## Masked files" in prompt and "- `/workspace/.env`\n- `/workspace/k.json`\n" in prompt


def test_gcp_auth_briefing(sb):
    prompt = stage(sb, "gcp-auth", GCP_SERVICE_ACCOUNT="sa@p.iam.gserviceaccount.com", GCP_PROJECT="p",
                   GCE_METADATA_HOST="127.0.0.1:4567").prompt
    assert "`sa@p.iam.gserviceaccount.com` (project `p`)" in prompt and "127.0.0.1:4567" in prompt


def test_kvm_briefing_includes_the_projects_own(sb):
    assert "KVM is available" in stage(sb, "kvm").prompt
    assert stage(sb, "kvm", KVM_BRIEFING="Images in /data.").prompt.endswith("\nImages in /data.\n")


@pytest.mark.parametrize("plugin, phrase", [
    ("libvirt", "`virsh` talks to the host's system daemon"),
    ("screenshots", "/home/node/Pictures/Screenshots"),
    ("package-managers", "sudo apt-get update"),
])
def test_static_briefings(sb, plugin, phrase):
    assert phrase in stage(sb, plugin).prompt
    assert sb.sh(f". {REPO}/plugins/{plugin}/agent-init.sh", AGENT_PROMPT_FILE="").ok().prompt == ""


@pytest.mark.parametrize("enrolled, phrase", [("1", "NetBird peer named sandbox-abc123"),
                                              ("0", "failed to join its NetBird mesh")])
def test_netbird_briefing(sb, enrolled, phrase):
    assert phrase in stage(sb, "netbird", NB_ENROLLED=enrolled, NB_PEER_NAME="sandbox-abc123").prompt


def test_package_managers_install_into_the_agents_home(sb):
    run = sb.sh(f'. {REPO}/plugins/package-managers/agent-init.sh\n'
                'echo "$NPM_CONFIG_PREFIX $PIP_BREAK_SYSTEM_PACKAGES"; echo "$PATH"').ok()
    prefix, path = run.out.splitlines()
    assert prefix == f"{sb.home}/.npm-global 1"
    assert path.startswith(f"{sb.home}/.npm-global/bin:{sb.home}/.local/bin:")
    assert (sb.home / ".npm-global/bin").is_dir() and (sb.home / ".local/bin").is_dir()


def test_ssh_credentials_writes_a_private_key_and_config(sb):
    run = stage(sb, "ssh-credentials", SSH_PRIVATE_KEY="-----BEGIN KEY-----\nbody\n-----END KEY-----",
                SSH_HOST_PATTERN="box-*", SSH_HOST_USER="ops", SSH_HOST_SUFFIX="mesh.internal")
    ssh = sb.home / ".ssh"
    assert (ssh / "sandbox_key").read_text() == "-----BEGIN KEY-----\nbody\n-----END KEY-----\n"
    for path, mode in ((ssh, 0o700), (ssh / "sandbox_key", 0o600), (ssh / "config", 0o600)):
        assert stat.S_IMODE(path.stat().st_mode) == mode, path
    assert (ssh / "config").read_text() == (
        "Host box-*\n    HostName %h.mesh.internal\n    User ops\n    IdentityFile ~/.ssh/sandbox_key\n"
        "    IdentitiesOnly yes\n    StrictHostKeyChecking accept-new\n")
    assert run.prompt == ("An SSH key for box-* is installed at ~/.ssh/sandbox_key and wired up in "
                          "~/.ssh/config, logging in as ops.\n")


def test_ssh_known_hosts_switch_on_strict_checking(sb):
    stage(sb, "ssh-credentials", SSH_PRIVATE_KEY="k", SSH_KNOWN_HOSTS="box ssh-ed25519 AAAA")
    assert (sb.home / ".ssh/known_hosts").read_text() == "box ssh-ed25519 AAAA\n"
    config = (sb.home / ".ssh/config").read_text()
    assert config.startswith("Host *\n") and "StrictHostKeyChecking yes" in config


def test_upstream_proxy_lists_the_proxied_endpoints(sb):
    assert stage(sb, "upstream-proxy").prompt == ""
    prompt = stage(sb, "upstream-proxy", UPSTREAM_PROXY_PORTS="api:8081 gcs:8083").prompt
    assert "- `api` at http://127.0.0.1:8081\n- `gcs` at http://127.0.0.1:8083\n" in prompt
    assert "placeholder keys" in prompt
