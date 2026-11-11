"""Each plugin's host.sh, and each agent's: what they validate and what they hand `docker run`."""
import glob
import os
import shutil
import signal
import socket
import subprocess

import pytest


# --- agents --------------------------------------------------------------------------------

def test_claude_needs_a_token(sb):
    sb.agent().dies("CLAUDE_CODE_OAUTH_TOKEN must be set")
    assert sb.agent(CLAUDE_CODE_OAUTH_TOKEN="tok").ok().env == {"CLAUDE_CODE_OAUTH_TOKEN": "tok"}


def test_claude_token_is_optional_when_a_plugin_brings_credentials(sb):
    assert sb.agent(AGENT_AUTH_PROVIDED=1).ok().args == []


@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max"])
def test_claude_effort_is_forwarded(sb, effort):
    assert sb.agent(AGENT_AUTH_PROVIDED=1, CLAUDE_EFFORT=effort).ok().env == {"CLAUDE_EFFORT": effort}


def test_claude_effort_is_validated(sb):
    sb.agent(AGENT_AUTH_PROVIDED=1, CLAUDE_EFFORT="turbo").dies("CLAUDE_EFFORT must be one of")


def test_copilot_needs_its_own_token(sb):
    sb.agent(AGENT="copilot").dies("COPILOT_GITHUB_TOKEN must be set")
    assert sb.agent(AGENT="copilot", COPILOT_GITHUB_TOKEN="pat").ok().env == {"COPILOT_GITHUB_TOKEN": "pat"}
    assert sb.agent(AGENT="copilot", AGENT_AUTH_PROVIDED=1).ok().args == []


@pytest.mark.parametrize("agent, plugin, var, target", [
    ("claude", "claude-home", "CLAUDE_HOME_DIR", "/home/node/.claude"),
    ("copilot", "copilot-home", "COPILOT_HOME_DIR", "/home/node/.copilot"),
])
def test_home_plugins_mount_the_host_config_and_replace_the_token(sb, agent, plugin, var, target):
    stage = f"ENABLED_PLUGINS={plugin}\nplugins_host_stage\nagent_resolve\nagent_host_stage"
    sb.bash(stage, AGENT=agent).dies("wants to mount")  # nothing at the default path yet
    default = sb.home / f".{agent}"
    default.mkdir()
    assert sb.bash(stage, AGENT=agent).ok().args == ["-v", f"{default}:{target}"]
    custom = sb.tmp / "elsewhere"
    custom.mkdir()
    assert sb.bash(stage, AGENT=agent, **{var: custom}).ok().mounts == [f"{custom}:{target}"]


# --- agent-workspace -----------------------------------------------------------------------

def test_agent_workspace_mounts_a_fresh_dir_and_removes_it_after(sb):
    mirrors = sb.tmp / "mirrors"
    run = sb.plugin("agent-workspace", AGENT_WORKSPACE_DIR=mirrors).ok()
    run_dir = mirrors / "project-20260102-abc123"
    assert run.mounts == [f"{run_dir}:/workspace"]
    assert not run_dir.exists()


def test_agent_workspace_cleanup_can_be_turned_off(sb):
    mirrors = sb.tmp / "mirrors"
    sb.plugin("agent-workspace", AGENT_WORKSPACE_DIR=mirrors, AGENT_WORKSPACE_CLEANUP=0).ok()
    assert (mirrors / "project-20260102-abc123").is_dir()


def test_agent_workspace_resume_reuses_and_empties_the_runs_dir(sb):
    old = sb.tmp / "mirrors/project-20251231-abc123"
    old.mkdir(parents=True)
    (old / "uncommitted.txt").write_text("x")
    run = sb.plugin("agent-workspace", AGENT_WORKSPACE_DIR=sb.tmp / "mirrors", RESUME=1,
                    AGENT_WORKSPACE_CLEANUP=0).ok()
    assert run.mounts == [f"{old}:/workspace"]
    assert "Clearing" in run.out
    assert list(old.iterdir()) == []


# --- ca-certs ------------------------------------------------------------------------------

def test_ca_certs_needs_certificates(sb):
    sb.plugin("ca-certs", CA_CERTS_DIR=sb.tmp / "none").dies("CA_CERTS_DIR not found")
    (sb.tmp / "empty").mkdir()
    sb.plugin("ca-certs", CA_CERTS_DIR=sb.tmp / "empty").dies("No certificates")


@pytest.fixture
def ca_dir(sb):
    d = sb.tmp / "cas"
    d.mkdir()
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=Test CA",
                    "-days", "1", "-keyout", sb.tmp / "k.pem", "-out", d / "pem.crt"],
                   check=True, capture_output=True)
    subprocess.run(["openssl", "x509", "-in", d / "pem.crt", "-outform", "DER", "-out", d / "der.crt"],
                   check=True, capture_output=True)
    return d


def test_ca_certs_mounts_and_bundles_pem_and_der(sb, ca_dir):
    run = sb.plugin("ca-certs", CA_CERTS_DIR=ca_dir).ok()
    assert run.mounts == [f"{ca_dir}:/opt/ca-certs:ro"]
    assert run.builds["EXTRA_CA_CERTS"].count("-----BEGIN CERTIFICATE-----") == 2


@pytest.mark.xfail(strict=True, reason="BUG: a file openssl cannot read fails the command "
                   "substitution, and set -e silently aborts run.sh (root-init.sh skips it instead)")
def test_ca_certs_skips_files_that_are_not_certificates(sb, ca_dir):
    (ca_dir / "README").write_text("not a certificate")
    sb.plugin("ca-certs", CA_CERTS_DIR=ca_dir).ok()


# --- cwd-workspace -------------------------------------------------------------------------

def test_cwd_workspace_mounts_the_checkout_and_masks_its_env(sb):
    sb.dotenv("SECRET=1\n")
    run = sb.plugin("cwd-workspace").ok()
    assert run.mounts == [f"{sb.cwd}:/workspace", "/dev/null:/workspace/.env:ro"]
    assert run.env == {"CWD_WORKSPACE_HIDDEN": "/workspace/.env"}
    assert (sb.cwd / ".env").read_text() == "SECRET=1\n"


def test_cwd_workspace_masks_only_listed_files_that_exist(sb):
    (sb.cwd / "secrets").mkdir()
    (sb.cwd / "secrets/key.json").write_text("{}")
    sb.dotenv("X=1\n")
    run = sb.plugin("cwd-workspace", CWD_WORKSPACE_HIDE="secrets/key.json missing.txt").ok()
    assert run.mounts[1:] == ["/dev/null:/workspace/secrets/key.json:ro"]
    assert sb.plugin("cwd-workspace", CWD_WORKSPACE_HIDE="").ok().mounts == [f"{sb.cwd}:/workspace"]


def test_cwd_workspace_dir_override(sb):
    run = sb.plugin("cwd-workspace", HOST_WORKSPACE_DIR=f"{sb.cwd}/../project/").ok()
    assert run.mounts == [f"{sb.cwd}:/workspace"]
    sb.plugin("cwd-workspace", HOST_WORKSPACE_DIR=sb.tmp / "nope").dies("is not a directory")


# --- data-mounts ---------------------------------------------------------------------------

def test_data_mounts(sb):
    for d in (sb.tmp / "datasets", sb.cwd / "rel/data", sb.home / "scratch"):
        d.mkdir(parents=True)
    sb.config({"plugins": {"data-mounts": {"mounts": [
        f"{sb.tmp}/datasets:/data:ro", "rel/data", "~/scratch:/scratch"]}}})
    assert sb.plugin("data-mounts").ok().mounts == [
        f"{sb.tmp}/datasets:/data:ro", f"{sb.cwd}/rel/data:{sb.cwd}/rel/data", f"{sb.home}/scratch:/scratch"]


@pytest.mark.parametrize("spec, message", [
    ("/no/such/dir:/data", "no such host path"),
    (".:data", "container path must be absolute"),
])
def test_data_mounts_validation(sb, spec, message):
    sb.config({"plugins": {"data-mounts": {"mounts": [spec]}}})
    sb.plugin("data-mounts").dies(message)


def test_data_mounts_without_config_does_nothing(sb):
    assert sb.plugin("data-mounts").ok().args == []


# --- docker-cli, kvm, libvirt, netbird: host devices and sockets ---------------------------

DOCKER_SOCK = "/var/run/docker.sock"


@pytest.mark.skipif(not os.path.exists(DOCKER_SOCK), reason="no Docker socket on this host")
def test_docker_cli_mounts_the_socket_with_its_group(sb):
    run = sb.plugin("docker-cli").ok()
    assert run.mounts == [f"{DOCKER_SOCK}:{DOCKER_SOCK}"]
    assert run.env == {"DOCKER_SOCKET_GID": str(os.stat(DOCKER_SOCK).st_gid)}


@pytest.mark.skipif(os.path.exists(DOCKER_SOCK), reason="this host has a Docker socket")
def test_docker_cli_needs_a_daemon(sb):
    sb.plugin("docker-cli").dies("/var/run/docker.sock not found")


@pytest.mark.skipif(not os.path.exists("/dev/kvm"), reason="no /dev/kvm on this host")
@pytest.mark.parametrize("briefing, expected", [
    (None, None), ("Images are in /data.", "Images are in /data."), (["one", "two"], "one\ntwo")])
def test_kvm_passes_the_device_and_the_projects_briefing(sb, briefing, expected):
    if briefing is not None:
        sb.config({"plugins": {"kvm": {"briefing": briefing}}})
    run = sb.plugin("kvm").ok()
    assert run.args[:2] == ["--device", "/dev/kvm"]
    assert run.env["KVM_DEVICE_GID"] == str(os.stat("/dev/kvm").st_gid)
    assert run.env.get("KVM_BRIEFING") == expected


@pytest.mark.skipif(os.path.exists("/dev/kvm"), reason="this host has /dev/kvm")
def test_kvm_needs_the_device(sb):
    sb.plugin("kvm").dies("/dev/kvm not found")


@pytest.mark.skipif(bool(glob.glob("/run/libvirt/*-sock")), reason="this host runs libvirt")
def test_libvirt_needs_a_daemon_socket(sb):
    sb.plugin("libvirt").dies("no libvirt socket under /run/libvirt")


@pytest.mark.skipif(not os.path.exists("/dev/net/tun"), reason="no /dev/net/tun on this host")
def test_netbird_gets_a_tun_device_and_its_setup_key(sb):
    run = sb.plugin("netbird", NB_SETUP_KEY="setup-key", NB_HOSTNAME="peer").ok()
    assert run.args[:2] == ["--cap-add=NET_ADMIN", "--device=/dev/net/tun"]
    assert run.env == {"NB_SETUP_KEY": "setup-key", "NB_HOSTNAME": "peer"}


@pytest.mark.skipif(os.path.exists("/dev/net/tun"), reason="this host has /dev/net/tun")
def test_netbird_needs_a_tun_device(sb):
    sb.plugin("netbird", NB_SETUP_KEY="k").dies("needs /dev/net/tun")


# --- gcp-auth ------------------------------------------------------------------------------

SA = "sandbox@my-proj.iam.gserviceaccount.com"


@pytest.mark.skipif(bool(shutil.which("gcloud")), reason="gcloud is installed on this host")
def test_gcp_auth_needs_gcloud_on_the_host(sb):
    sb.plugin("gcp-auth", GCP_SERVICE_ACCOUNT=SA).dies("gcloud is required on the host")


def test_gcp_auth_registers_a_token_for_the_service_account(sb):
    sb.stub("gcloud", "exit 0\n")
    run = sb.bash("ENABLED_PLUGINS=gcp-auth\nplugins_host_stage\nprintf '%s\\n' \"${CREDENTIALS[@]}\"",
                  GCP_SERVICE_ACCOUNT=SA).ok()
    assert run.env == {"GCP_SERVICE_ACCOUNT": SA, "GCP_PROJECT": "my-proj"}
    assert "gcp-token 2400 gcp_auth_mint" in run.out


def test_gcp_auth_mint_runs_the_minter_with_the_account(sb):
    sb.stub("gcloud", "exit 0\n")
    fake = sb.tmp / "fake-plugin"
    (fake / "host").mkdir(parents=True)
    (fake / "host/mint-gcp-token.py").write_text('#!/bin/sh\necho "minted for $GCP_SERVICE_ACCOUNT"\n')
    (fake / "host/mint-gcp-token.py").chmod(0o755)
    run = sb.bash(f"ENABLED_PLUGINS=gcp-auth\nplugins_host_stage\nGCP_AUTH_DIR={fake}\ngcp_auth_mint",
                  GCP_SERVICE_ACCOUNT=SA).ok()
    assert run.out.endswith(f"minted for {SA}\n")


@pytest.mark.parametrize("account, project, outcome", [
    ("me@gmail.com", None, "must be a service account email"),
    ("123-compute@developer.gserviceaccount.com", None, "set GCP_PROJECT"),
    ("123-compute@developer.gserviceaccount.com", "explicit", "explicit"),
    (SA, "override", "override"),
])
def test_gcp_auth_account_and_project(sb, account, project, outcome):
    sb.stub("gcloud", "exit 0\n")
    run = sb.plugin("gcp-auth", GCP_SERVICE_ACCOUNT=account, GCP_PROJECT=project)
    if outcome in ("explicit", "override"):
        assert run.ok().env["GCP_PROJECT"] == outcome
    else:
        run.dies(outcome)


# --- git-workspace -------------------------------------------------------------------------

GIT_ENV = {"PATH": os.environ["PATH"], "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}


def git(*args, cwd):
    return subprocess.run(["git", *map(str, args)], cwd=cwd, env=GIT_ENV, check=True,
                          capture_output=True, text=True).stdout


def checkout_with_origin(sb, branch="main"):
    origin = sb.tmp / "origin.git"
    git("init", "-q", "--bare", "-b", branch, origin, cwd=sb.tmp)
    git("clone", "-q", origin, sb.tmp / "seed", cwd=sb.tmp)
    git("commit", "-q", "--allow-empty", "-m", "init", cwd=sb.tmp / "seed")
    git("push", "-q", "origin", f"HEAD:{branch}", cwd=sb.tmp / "seed")
    git("clone", "-q", origin, sb.cwd, cwd=sb.tmp)
    return origin


def test_git_workspace_needs_a_checkout_with_an_origin(sb):
    sb.plugin("git-workspace").dies("is not a git repository")
    git("init", "-q", sb.cwd, cwd=sb.tmp)
    sb.plugin("git-workspace").dies("has no 'origin' remote")


def test_git_workspace_hands_over_the_repo_and_its_default_branch(sb):
    origin = checkout_with_origin(sb)
    assert sb.plugin("git-workspace").ok().env == {"REPO_URL": str(origin), "BASE_BRANCH": "main"}


def test_git_workspace_finds_a_default_branch_not_called_main(sb):
    checkout_with_origin(sb, branch="trunk")
    assert sb.plugin("git-workspace").ok().env["BASE_BRANCH"] == "trunk"
    git("remote", "set-head", "origin", "-d", cwd=sb.cwd)  # no origin/HEAD: ask the remote
    assert sb.plugin("git-workspace").ok().env["BASE_BRANCH"] == "trunk"


def test_git_workspace_base_branch_must_exist_on_origin(sb):
    checkout_with_origin(sb)
    assert sb.plugin("git-workspace", BASE_BRANCH="main").ok().env["BASE_BRANCH"] == "main"
    sb.plugin("git-workspace", BASE_BRANCH="nope").dies("origin has no branch 'nope'")


def test_git_workspace_branch_prefix_precedence(sb):
    checkout_with_origin(sb)
    prefix = lambda **env: sb.plugin("git-workspace", **env).ok().env.get("BRANCH_PREFIX")  # noqa: E731
    assert prefix() is None
    assert prefix(BRANCH_PREFIX="from-shell") == "from-shell"
    sb.dotenv("BRANCH_PREFIX=from-dotenv\n")
    assert prefix(BRANCH_PREFIX="from-shell") == "from-dotenv"
    sb.config({"plugins": {"git-workspace": {"branchPrefix": "from-config"}}})
    assert prefix(BRANCH_PREFIX="from-shell") == "from-config"


# --- github-auth ---------------------------------------------------------------------------

def test_github_auth_needs_the_key_file(sb):
    sb.plugin("github-auth", GH_APP_ID=1, GH_PRIVATE_KEY_FILE=sb.tmp / "none.pem").dies("GH_PRIVATE_KEY_FILE not found")


def test_github_auth_registers_a_token_and_never_passes_the_key(sb):
    key = sb.tmp / "app.pem"
    key.write_text("-----BEGIN RSA PRIVATE KEY-----\nsecret\n")
    show = "ENABLED_PLUGINS=github-auth\nplugins_host_stage\nprintf '%s\\n' \"${CREDENTIALS[@]}\""
    run = sb.bash(show, GH_APP_ID=1, GH_PRIVATE_KEY_FILE=key).ok()
    assert run.env == {"GH_HOST": "github.com"}
    assert "github-token 2400 github_auth_mint" in run.out
    assert not any("secret" in a or str(key) in a for a in run.args)
    run = sb.bash(show, GH_APP_ID=1, GH_PRIVATE_KEY_FILE=key, GH_HOST="ghe.example.com", GH_USERNAME="bot").ok()
    assert run.env == {"GH_HOST": "ghe.example.com", "GH_USERNAME": "bot"}


def test_github_auth_mint_sees_the_repo_url_set_by_later_plugins(sb):
    key = sb.tmp / "app.pem"
    key.write_text("k")
    fake = sb.tmp / "fake-plugin"
    (fake / "host").mkdir(parents=True)
    (fake / "host/mint-gh-token.py").write_text('#!/bin/sh\necho "$GH_APP_ID $GH_PRIVATE_KEY_FILE $GH_HOST $REPO_URL"\n')
    (fake / "host/mint-gh-token.py").chmod(0o755)
    run = sb.bash(f"ENABLED_PLUGINS=github-auth\nplugins_host_stage\nGITHUB_AUTH_DIR={fake}\n"
                  "REPO_URL=https://github.com/acme/w.git\ngithub_auth_mint", GH_APP_ID=7, GH_PRIVATE_KEY_FILE=key).ok()
    assert run.out.endswith(f"7 {key} github.com https://github.com/acme/w.git\n")


# --- herdr, host-network, screenshots ------------------------------------------------------

@pytest.mark.parametrize("herdr_env, expected", [("1", "HERDR_AGENT=copilot"), (None, "")])
def test_herdr_labels_the_docker_process_inside_a_herdr_pane(sb, herdr_env, expected):
    run = sb.bash("ENABLED_PLUGINS=herdr\nplugins_host_stage\nenv | grep '^HERDR_AGENT=' || true",
                  HERDR_ENV=herdr_env, AGENT="copilot").ok()
    assert run.out.strip() == expected
    assert run.args == []


def test_host_network(sb):
    assert sb.plugin("host-network").ok().args == ["--network", "host"]


def test_screenshots_mounts_read_only(sb):
    sb.plugin("screenshots").dies("no such directory")
    default = sb.home / "Pictures/Screenshots"
    default.mkdir(parents=True)
    assert sb.plugin("screenshots").ok().mounts == [f"{default}:/home/node/Pictures/Screenshots:ro"]
    (sb.tmp / "shots").mkdir()
    assert sb.plugin("screenshots", SCREENSHOTS_DIR=sb.tmp / "shots").ok().mounts == [
        f"{sb.tmp}/shots:/home/node/Pictures/Screenshots:ro"]


# --- project-deps --------------------------------------------------------------------------

def test_project_deps_without_config_installs_nothing(sb):
    run = sb.plugin("project-deps").ok()
    assert run.args == [] and "nothing configured" in run.out


def test_project_deps_hands_over_validated_lists(sb):
    sb.config({"plugins": {"project-deps": {
        "apt": ["ripgrep", "postgresql-client"], "npm": ["pnpm@9", "./local-pkg"],
        "pip": ["ruff==0.6.*", "pkg>=1.0", "git+https://github.com/a/b"],
        "setup": ["pnpm install --frozen-lockfile", "make bootstrap && echo $HOME"]}}})
    run = sb.plugin("project-deps").ok()
    assert run.env == {
        "PROJECT_DEPS_APT": "ripgrep postgresql-client",
        "PROJECT_DEPS_NPM": "pnpm@9 ./local-pkg",
        "PROJECT_DEPS_PIP": "ruff==0.6.* pkg>=1.0 git+https://github.com/a/b",
        "PROJECT_DEPS_SETUP": '["pnpm install --frozen-lockfile","make bootstrap && echo $HOME"]',
    }
    assert "2 setup command(s)" in run.out


@pytest.mark.parametrize("name", ["two words", "x;reboot", "$(id)", "`id`", "a|b", "a&b", "'q'"])
def test_project_deps_rejects_anything_but_a_package_name(sb, name):
    sb.config({"plugins": {"project-deps": {"apt": [name]}}})
    sb.plugin("project-deps").dies("is not a valid apt package name")


@pytest.mark.parametrize("key, value", [("pip", "ruff"), ("npm", [1]), ("setup", "make"), ("setup", [["x"]])])
def test_project_deps_lists_must_be_arrays_of_strings(sb, key, value):
    sb.config({"plugins": {"project-deps": {key: value}}})
    sb.plugin("project-deps").dies("must be an array of strings")


# --- ssh-credentials -----------------------------------------------------------------------

KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaA==\n-----END OPENSSH PRIVATE KEY-----\n"


@pytest.mark.parametrize("content, message", [
    (None, "SSH_PRIVATE_KEY_FILE not found"),
    ("ssh-ed25519 AAAA user@host\n", "does not look like a private key"),
    ("-----BEGIN RSA PRIVATE KEY-----\nProc-Type: 4,ENCRYPTED\n", "passphrase-protected"),
])
def test_ssh_credentials_validates_the_key(sb, content, message):
    key = sb.tmp / "key"
    if content is not None:
        key.write_text(content)
    sb.plugin("ssh-credentials", SSH_PRIVATE_KEY_FILE=key).dies(message)


def test_ssh_credentials_passes_the_key_config_and_known_hosts(sb):
    (sb.tmp / "key").write_text(KEY)
    (sb.tmp / "known").write_text("host ssh-ed25519 AAAA\n")
    run = sb.plugin("ssh-credentials", SSH_PRIVATE_KEY_FILE=sb.tmp / "key", SSH_HOST_PATTERN="box-*",
                    SSH_HOST_USER="ops", SSH_KNOWN_HOSTS_FILE=sb.tmp / "known").ok()
    assert run.env == {"SSH_PRIVATE_KEY": KEY.rstrip("\n"), "SSH_HOST_PATTERN": "box-*",
                       "SSH_HOST_USER": "ops", "SSH_KNOWN_HOSTS": "host ssh-ed25519 AAAA"}
    sb.plugin("ssh-credentials", SSH_PRIVATE_KEY_FILE=sb.tmp / "key",
              SSH_KNOWN_HOSTS_FILE=sb.tmp / "nope").dies("SSH_KNOWN_HOSTS_FILE not found")


# --- upstream-proxy ------------------------------------------------------------------------

def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def proxy_sb(sb, short_tmp):
    """upstream-proxy's shared dirs live under TMPDIR; keep them away from any real sandbox's."""
    sb.env["TMPDIR"] = str(short_tmp)
    yield sb
    for pid_file in glob.glob(f"{short_tmp}/upstream-proxy-*/proxy.pid"):
        try:
            os.kill(int(open(pid_file).read()), signal.SIGKILL)
        except (OSError, ValueError):
            pass


def proxy_dirs(sb):
    return glob.glob(f"{sb.env['TMPDIR']}/upstream-proxy-{os.getuid()}-*")


def routes(port=18080, **extra):
    return [{"name": "api", "port": port, "upstream": "http://127.0.0.1:9", **extra}]


def test_upstream_proxy_without_routes_does_nothing(proxy_sb):
    run = proxy_sb.plugin("upstream-proxy").ok()
    assert run.args == [] and "no routes configured" in run.out
    assert proxy_dirs(proxy_sb) == []


def test_upstream_proxy_routes_must_be_a_list(proxy_sb):
    proxy_sb.config({"plugins": {"upstream-proxy": {"routes": {"name": "api"}}}})
    proxy_sb.plugin("upstream-proxy").dies("must be an array")


def test_upstream_proxy_starts_a_proxy_and_hands_over_only_sockets_and_env(proxy_sb):
    proxy_sb.dotenv("DEPLOYMENT=gpt-x\nAPI_SECRET=hunter2\n")
    proxy_sb.config({"plugins": {"upstream-proxy": {"routes": routes(
        auth={"type": "bearer", "valueEnv": "API_SECRET"},
        containerEnv={"API_URL": "http://127.0.0.1:18080", "DEPLOY": "${DEPLOYMENT}",
                      "FROM_HOST": "${HOST_ONLY}", "MISSING": "x${NOPE}y"})}}})
    run = proxy_sb.plugin("upstream-proxy", HOST_ONLY="h").ok()
    [proxy_dir] = proxy_dirs(proxy_sb)
    assert run.mounts == [f"{proxy_dir}/sockets:/run/upstream-proxy"]
    assert run.env == {"UPSTREAM_PROXY_PORTS": "api:18080", "API_URL": "http://127.0.0.1:18080",
                       "DEPLOY": "gpt-x", "FROM_HOST": "h", "MISSING": "xy"}
    assert not any("hunter2" in a for a in run.args)
    # The last run.sh to leave stops the proxy and clears everything but the lock.
    assert os.listdir(proxy_dir) == ["lock"]


def test_upstream_proxy_is_shared_while_another_run_uses_it(proxy_sb):
    proxy_sb.config({"plugins": {"upstream-proxy": {"routes": routes()}}})
    # A second, still-running run.sh of the project: this test process stands in for it.
    run = proxy_sb.bash(f"project_config_load\nENABLED_PLUGINS=upstream-proxy\nplugins_host_stage\n"
                        f': >"$UPSTREAM_PROXY_USERS/{os.getpid()}"').ok()
    [proxy_dir] = proxy_dirs(proxy_sb)
    pid = int(open(f"{proxy_dir}/proxy.pid").read())
    os.kill(pid, 0)  # still running
    again = proxy_sb.plugin("upstream-proxy").ok()
    assert "sharing the proxy" in again.out
    assert again.mounts == run.mounts
    assert int(open(f"{proxy_dir}/proxy.pid").read()) == pid


def test_upstream_proxy_sweeps_orphans_of_other_configs(proxy_sb):
    orphan = f"{proxy_sb.env['TMPDIR']}/upstream-proxy-{os.getuid()}-deadbeef0000"
    os.makedirs(f"{orphan}/users")
    open(f"{orphan}/users/999999999", "w").close()  # a run.sh killed before its exit hook
    stale = subprocess.Popen(["sleep", "60"])
    open(f"{orphan}/proxy.pid", "w").write(str(stale.pid))
    proxy_sb.config({"plugins": {"upstream-proxy": {"routes": routes()}}})
    proxy_sb.plugin("upstream-proxy").ok()
    assert stale.wait(timeout=5) == -signal.SIGTERM
    assert os.listdir(orphan) == ["lock"]


def test_upstream_proxy_reports_a_proxy_that_cannot_start(proxy_sb):
    proxy_sb.config({"plugins": {"upstream-proxy": {"routes": routes(allowMethods=[])}}})
    proxy_sb.plugin("upstream-proxy").dies("the proxy exited during startup")


def test_upstream_proxy_under_host_network_holds_the_ports_itself(proxy_sb):
    proxy_sb.stub("docker", "echo 'Ubuntu 24.04 LTS'\n")
    port = free_port()
    proxy_sb.config({"plugins": {"upstream-proxy": {"routes": routes(port=port)}}})
    run = proxy_sb.bash("project_config_load\nENABLED_PLUGINS='host-network upstream-proxy'\n"
                        f"plugins_host_stage\nbash -c 'exec 3<>/dev/tcp/127.0.0.1/{port}' && echo listening").ok()
    [proxy_dir] = proxy_dirs(proxy_sb)
    assert run.mounts == [f"{proxy_dir}/attest:/run/upstream-proxy-attest"]
    assert run.env["UPSTREAM_PROXY_ATTEST_DIR"] == "/run/upstream-proxy-attest"
    assert "listening" in run.out


def test_upstream_proxy_on_docker_desktop_forwards_per_container(proxy_sb):
    proxy_sb.stub("docker", "echo 'Docker Desktop'\n")
    proxy_sb.config({"plugins": {"upstream-proxy": {"routes": routes()}}})
    run = proxy_sb.bash("project_config_load\nENABLED_PLUGINS='host-network upstream-proxy'\nplugins_host_stage").ok()
    [proxy_dir] = proxy_dirs(proxy_sb)
    assert f"{proxy_dir}/sockets:/run/upstream-proxy" in run.mounts
    assert "UPSTREAM_PROXY_ATTEST_DIR" not in run.env
