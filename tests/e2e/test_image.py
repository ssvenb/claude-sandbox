"""Boot the real image: everything that needs root, a PID namespace or the image's own layout.

Needs a sandbox image built from the Dockerfile with every plugin installed (ENABLED_PLUGINS
empty), named by SANDBOX_E2E_IMAGE; SANDBOX_E2E_AGENT says which agent it was built for. A
test layer (tests/e2e/Dockerfile) adds a stand-in agent that reports how it was launched and then
runs a probe as the agent user.
"""
import json
import os
import subprocess
import time
import uuid

import pytest

from conftest import REPO

BASE = os.environ.get("SANDBOX_E2E_IMAGE")
AGENT = os.environ.get("SANDBOX_E2E_AGENT", "claude")
MANAGED = json.loads((REPO / "agents" / AGENT / "agent.json").read_text())["managedSettings"]
PREFIX = json.loads((REPO / "agents" / AGENT / "agent.json").read_text())["git"]["branchPrefix"]
pytestmark = pytest.mark.skipif(not BASE, reason="SANDBOX_E2E_IMAGE is not set")
claude_only = pytest.mark.skipif(AGENT != "claude", reason="claude-only plugin")


@pytest.fixture(scope="module")
def image():
    tag = f"sandbox-e2e-test:{AGENT}"
    done = subprocess.run(["docker", "build", "-q", "-t", tag, "--build-arg", f"IMAGE={BASE}",
                           "-f", "tests/e2e/Dockerfile", "."], cwd=REPO, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return tag


class Boot:
    def __init__(self, stdout, stderr, code):
        self.code = code
        before, marker, after = stdout.partition("E2E-REPORT ")
        assert marker, f"the agent never started (exit {code}):\n{stdout}\n{stderr}"
        line, _, self.out = after.partition("\n")
        self.log = before + stderr
        report = json.loads(line)
        self.argv, self.env, self.uid = report["argv"], report["env"], report["uid"]
        self.groups, self.cwd = report["groups"], report["cwd"]

    @property
    def briefing(self) -> str:
        flag = "--append-system-prompt" if AGENT == "claude" else "-i"
        return self.argv[self.argv.index(flag) + 1] if flag in self.argv else ""


def run_args(plugins, probe, env):
    env = {"ENABLED_PLUGINS": plugins, "AGENT_LAUNCH_CMD": "fake-agent", "AGENT": AGENT,
           "RUN_ID": "abc123", "RUN_DATE": "20260102", "RESUME": "0", "E2E_PROBE": probe, **env}
    return [arg for k, v in env.items() for arg in ("-e", f"{k}={v}")]


def boot(image, plugins="", probe="", before=None, **env) -> Boot:
    """One sandbox boot, start to finish. `before` runs as root ahead of the entrypoint."""
    cmd = ["docker", "run", "--rm", *run_args(plugins, probe, env)]
    if before:
        cmd += ["--entrypoint", "sh", image, "-c", f"{before}\nexec /usr/local/bin/entrypoint.sh"]
    else:
        cmd.append(image)
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    return Boot(done.stdout, done.stderr, done.returncode)


def test_bare_boot_drops_to_the_agent_user(image):
    b = boot(image, probe=f'cat {MANAGED}; echo; stat -c "%U %a" {MANAGED}', CLAUDE_EFFORT="high")
    assert (b.uid, b.cwd, b.env["HOME"]) == (1000, "/workspace", "/home/node")
    assert b.argv == (["--dangerously-skip-permissions", "--effort", "high"] if AGENT == "claude"
                      else ["--allow-all"])
    settings, mode = b.out.strip().rsplit("\n", 1)
    assert (json.loads(settings), mode) == ({}, "root 444")


def test_the_agent_cli_and_every_plugins_tools_are_installed(image):
    tools = ["/usr/bin/gh", "docker", "gcloud", "qemu-img", "cloud-localds", "virsh", "ssh", "sudo",
             "terraform", "chromium", "/usr/local/bin/netbird", AGENT]
    if AGENT == "claude":
        tools.append("playwright-mcp")
    probe = (f"for t in {' '.join(tools)}; do command -v $t >/dev/null || echo missing $t; done\n"
             f"ls /usr/bin/qemu-system-* >/dev/null || echo missing qemu-system\n"
             f"{AGENT} --version >/dev/null || echo broken {AGENT}")
    assert boot(image, probe=probe).out == ""


def test_the_agent_cannot_touch_its_guardrails(image):
    probe = f"""touch /opt/plugins/x 2>/dev/null && echo plugins writable
touch /opt/agents/x 2>/dev/null && echo agents writable
cat /opt/plugins/gcp-auth/root/metadata.py >/dev/null 2>&1 && echo root helper readable
rm -f {MANAGED} 2>/dev/null; [ -f {MANAGED} ] || echo policy removed
[ -x /opt/plugins/branch-guard/bin/guard-branch.py ] || echo hook not executable"""
    assert boot(image, "branch-guard", probe).out == ""


def test_declared_secrets_never_reach_the_agent(image):
    b = boot(image, "netbird", "cat /var/log/netbird-up.args", NB_SETUP_KEY="e2e-setup-key",
             NB_MANAGEMENT_URL="https://nb.example")
    assert "NB_SETUP_KEY" not in b.env and "e2e-setup-key" not in json.dumps(b.env)
    assert b.out.strip() == ("up --setup-key e2e-setup-key --hostname sandbox-abc123 "
                             "--management-url https://nb.example")
    assert b.env["NB_ENROLLED"] == "1" and "NetBird peer named sandbox-abc123" in b.briefing


def test_a_failed_netbird_enrolment_still_boots(image):
    b = boot(image, "netbird", NB_SETUP_KEY="k", E2E_NETBIRD_FAIL=1)
    assert b.env["NB_ENROLLED"] == "0" and "failed to join its NetBird mesh" in b.briefing


GIT_PROBE = ("cd /workspace; git rev-parse --abbrev-ref HEAD; git config user.name; git config user.email; "
             "git log -1 --format=%s; stat -c %U .")


def test_git_workspace_creates_the_runs_branch(image):
    plugins = "git-workspace branch-guard" if AGENT == "claude" else "git-workspace"
    b = boot(image, plugins, GIT_PROBE, REPO_URL="/srv/origin.git", BASE_BRANCH="main")
    branch = f"{PREFIX}/20260102-abc123"
    name = json.loads((REPO / "agents" / AGENT / "agent.json").read_text())["git"]["userName"]
    assert b.out.splitlines() == [branch, name, f"{AGENT}@sandbox.local", "initial", "node"]
    assert (b.env["AGENT_BRANCH"], b.env["AGENT_BRANCH_PREFIX"]) == (branch, PREFIX)
    assert f"on the branch {branch}, created for this sandbox run (RUN_ID=abc123) off main" in b.briefing
    assert ("You cannot leave this branch" if AGENT == "claude" else "Stay on this branch") in b.briefing


def test_an_explicit_branch_prefix_is_also_the_identity(image):
    b = boot(image, "git-workspace", GIT_PROBE, REPO_URL="/srv/origin.git", BASE_BRANCH="main",
             BRANCH_PREFIX="feature")
    assert b.out.splitlines()[:3] == ["feature/20260102-abc123", "feature", "feature@sandbox.local"]


def test_resume_finds_the_runs_branch_and_its_pull_request(image):
    b = boot(image, "git-workspace", GIT_PROBE, REPO_URL="/srv/origin.git", BASE_BRANCH="main",
             RESUME=1, RUN_ID="dead01")
    assert b.out.splitlines()[0] == "claude-code/20251231-dead01"   # the day it was created
    assert b.out.splitlines()[3] == "previous work"
    assert "resuming an existing sandbox run (RUN_ID=dead01) on its existing branch claude-code/20251231-dead01" \
        in b.briefing
    assert "A pull request already exists for this branch (#7 https://github.com/e2e/repo/pull/7)" in b.briefing


@claude_only
def test_branch_guard_hook_is_installed_and_enforces_the_branch(image):
    hook = "/opt/plugins/branch-guard/bin/guard-branch.py"
    probe = f"""cat {MANAGED}; echo
printf '%s' '{{"tool_input": {{"command": "git checkout main"}}}}' | {hook} 2>/dev/null; echo "checkout=$?"
printf '{{"tool_input": {{"command": "git push origin %s"}}}}' "$AGENT_BRANCH" | {hook}; echo "own=$?"
printf '%s' '{{"tool_input": {{"command": "git push origin main"}}}}' | {hook} 2>/dev/null; echo "main=$?" """
    b = boot(image, "git-workspace branch-guard", probe, REPO_URL="/srv/origin.git", BASE_BRANCH="main")
    *settings, checkout, own, main = b.out.strip().splitlines()
    assert json.loads("\n".join(settings))["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == hook
    assert (checkout, own, main) == ("checkout=2", "own=0", "main=2")


def test_github_auth_logs_gh_in_with_the_minted_token(image):
    b = boot(image, "github-auth", "cat /tmp/gh.log", GH_HOST="github.com", GH_USERNAME="e2e-bot")
    assert b.out.splitlines() == ["auth login --hostname github.com --with-token | ghs_e2e",
                                  "config set -h github.com user e2e-bot",
                                  "auth setup-git --hostname github.com"]


def test_ca_certs_joins_the_trust_store(image):
    bundle = "/etc/ssl/certs/ca-certificates.crt"
    probe = (f"openssl verify -CAfile {bundle} /opt/ca-certs/e2e-pem.crt\n"
             f"openssl x509 -inform DER -in /opt/ca-certs/e2e-der.cer -out /tmp/der.pem && "
             f"openssl verify -CAfile {bundle} /tmp/der.pem")
    b = boot(image, "ca-certs", probe)
    assert b.out.splitlines() == ["/opt/ca-certs/e2e-pem.crt: OK", "/tmp/der.pem: OK"]
    assert "added 2 extra CA certificate(s)" in b.log and "Skipping /opt/ca-certs/README" in b.log
    assert b.env["NODE_EXTRA_CA_CERTS"] == b.env["SSL_CERT_FILE"] == b.env["REQUESTS_CA_BUNDLE"] == bundle


def test_device_and_socket_groups_reach_the_agent(image):
    b = boot(image, "docker-cli kvm", "id -nG", DOCKER_SOCKET_GID=4242, KVM_DEVICE_GID=100)
    assert {4242, 100} <= set(b.groups)
    assert {"docker-host", "users"} <= set(b.out.split())


def test_package_managers(image):
    probe = ("sudo -n apt-get --version >/dev/null && echo apt-ok\n"
             "sudo -n /usr/bin/id >/dev/null 2>&1 || echo id-refused\nnpm config get prefix")
    b = boot(image, "package-managers", probe)
    assert b.out.splitlines() == ["apt-ok", "id-refused", "/home/node/.npm-global"]
    assert b.env["PATH"].startswith("/home/node/.npm-global/bin:/home/node/.local/bin:")


def test_project_deps_install_as_root_and_set_up_as_the_agent(image):
    probe = "e2e-npm; python3 -c 'import e2e_pkg; print(e2e_pkg.OK)'; cat /workspace/setup-user /workspace/setup-cwd"
    setup = ["id -un > setup-user", "false", "pwd > setup-cwd"]
    b = boot(image, "git-workspace project-deps", probe, REPO_URL="/srv/origin.git", BASE_BRANCH="main",
             PROJECT_DEPS_NPM="/opt/e2e/npm-pkg", PROJECT_DEPS_PIP="/opt/e2e/e2e_pkg-1.0-py3-none-any.whl",
             PROJECT_DEPS_APT="e2e-no-such-package", PROJECT_DEPS_SETUP=json.dumps(setup))
    assert b.out.splitlines() == ["npm-ok", "pip-ok", "node", "/workspace"]
    assert "apt install failed (e2e-no-such-package)" in b.log       # reported, not fatal
    assert "setup command failed: false" in b.log
    assert "already run for you in /workspace during boot (id -un > setup-user; false; pwd > setup-cwd)" \
        in b.briefing


def test_ssh_credentials_belong_to_the_agent_user(image):
    b = boot(image, "ssh-credentials", "stat -c '%U %a' ~/.ssh/sandbox_key; ssh -G box | grep -E '^(hostname|user|identityfile) '",
             SSH_PRIVATE_KEY="-----BEGIN OPENSSH PRIVATE KEY-----\nx\n-----END OPENSSH PRIVATE KEY-----",
             SSH_HOST_PATTERN="box", SSH_HOST_USER="ops", SSH_HOST_SUFFIX="mesh")
    assert b.out.splitlines() == ["node 600", "user ops", "hostname box.mesh", "identityfile ~/.ssh/sandbox_key"]


def test_entrypoint_hands_the_workspace_to_the_agent_but_not_masks(image):
    b = boot(image, "cwd-workspace", "stat -c %U /workspace/sub /workspace/sub/f; stat -c '%U %F' /workspace/.env",
             before="mkdir /workspace/sub && touch /workspace/sub/f && mknod /workspace/.env c 1 3",
             CWD_WORKSPACE_HIDDEN="/workspace/.env")
    assert b.out.splitlines() == ["node", "node", "root character special file"]
    assert "- `/workspace/.env`" in b.briefing


def test_gcp_auth_serves_the_hosts_token_as_a_metadata_server(image):
    url = "http://$GCE_METADATA_HOST/computeMetadata/v1/instance/service-accounts/default/token"
    b = boot(image, "gcp-auth", f"curl -sf -H 'Metadata-Flavor: Google' {url}",
             GCP_SERVICE_ACCOUNT="sa@e2e-proj.iam.gserviceaccount.com", GCP_PROJECT="e2e-proj")
    token = json.loads(b.out)
    assert token["access_token"] == "ya29.e2e" and 0 < token["expires_in"] <= 3600
    assert b.env["CLOUDSDK_AUTH_ACCESS_TOKEN_FILE"] == "/run/credentials/gcp-token"
    assert b.env["CLOUDSDK_CORE_PROJECT"] == b.env["GOOGLE_CLOUD_PROJECT"] == "e2e-proj"
    assert "`sa@e2e-proj.iam.gserviceaccount.com` (project `e2e-proj`)" in b.briefing


def test_gcp_auth_without_a_token_fails_the_boot(image):
    cmd = ["docker", "run", "--rm", *run_args("gcp-auth", "", {"GCP_SERVICE_ACCOUNT": "sa@p.iam.gserviceaccount.com",
                                                               "GCP_PROJECT": "p"}),
           "--entrypoint", "sh", image, "-c", "rm /run/credentials/gcp-token; exec /usr/local/bin/entrypoint.sh"]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert done.returncode == 1 and "gcp-token is missing" in done.stderr
    assert "E2E-REPORT" not in done.stdout


UPSTREAM = {"UPSTREAM_PROXY_PORTS": "api:8099"}
ATTEST = {**UPSTREAM, "UPSTREAM_PROXY_ATTEST_DIR": "/run/upstream-proxy-attest"}


@pytest.mark.parametrize("mode", [UPSTREAM, ATTEST], ids=["forwarded", "host-network"])
def test_upstream_proxy_reaches_the_upstream_with_the_hosts_credential(image, mode):
    b = boot(image, "e2e-upstream upstream-proxy",
             "curl -sf -H 'Authorization: Bearer placeholder' http://127.0.0.1:8099/hello", **mode)
    seen = json.loads(b.out)
    assert seen["path"] == "/hello" and seen["headers"]["Authorization"] == "Bearer upstream-secret"
    assert "upstream-secret" not in json.dumps(b.env)
    assert "- `api` at http://127.0.0.1:8099" in b.briefing


@pytest.mark.parametrize("mode", [UPSTREAM, ATTEST], ids=["forwarded", "host-network"])
def test_processes_outside_the_sandbox_are_refused_on_its_loopback(image, mode):
    """A second container in the first one's network namespace, but its own PID namespace, is
    exactly what another sandbox under host-network is: it must not use these ports."""
    name = f"sandbox-e2e-{uuid.uuid4().hex[:8]}"
    env = {**mode, "GCP_SERVICE_ACCOUNT": "sa@e2e-proj.iam.gserviceaccount.com", "GCP_PROJECT": "e2e-proj"}
    subprocess.run(["docker", "run", "-d", "--name", name, *run_args("e2e-upstream upstream-proxy gcp-auth",
                                                                    "sleep 300", env), image],
                   check=True, capture_output=True)
    try:
        deadline = time.time() + 120
        while "E2E-REPORT " not in (logs := subprocess.run(["docker", "logs", name], capture_output=True,
                                                           text=True).stdout):
            assert time.time() < deadline, logs
            time.sleep(0.5)
        metadata = json.loads(logs.split("E2E-REPORT ", 1)[1].splitlines()[0])["env"]["GCE_METADATA_HOST"]
        project = f"http://{metadata}/computeMetadata/v1/project/project-id"

        def curl(*prefix, url):
            done = subprocess.run([*prefix, "curl", "-s", "-i", "-m", "10", "-H", "Metadata-Flavor: Google", url],
                                  capture_output=True, text=True)
            return done.stdout
        inside = ("docker", "exec", "-u", "node", name)
        neighbour = ("docker", "run", "--rm", f"--network=container:{name}", "--entrypoint", "", image)
        assert "200 OK" in curl(*inside, url="http://127.0.0.1:8099/x")
        assert curl(*inside, url=project).endswith("e2e-proj")
        assert curl(*neighbour, url="http://127.0.0.1:8099/x").startswith("HTTP/1.1 403 Forbidden")
        assert curl(*neighbour, url=project) == ""   # dropped without an answer
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
