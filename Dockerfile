# glibc base (Debian) — NOT alpine/musl. headroom-ai is a maturin (Rust) package and
# only ships glibc `manylinux` wheels on PyPI; on musl pip would fall back to building
# from Rust source. node:20-bookworm-slim gives us prebuilt wheels for headroom-ai +
# tiktoken with no toolchain, and Claude Code (the npm package) too.
FROM node:20-bookworm-slim

# Install automation dependencies and system utilities. github-cli and docker-cli live
# in their own apt repos, added below; everything else is in Debian main.
RUN apt-get update && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        gnupg \
        jq \
        openssl \
        git \
        python3 \
        python3-venv \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

# GitHub CLI (gh) — used by the agent to authenticate git and drive GitHub workflows.
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# Docker CLI + compose plugin (client only — the daemon, if any, is the host's, reached via a
# mounted socket). From Docker's official apt repo.
RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg \
        -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

# Headroom compression proxy, driven by the `headroom` plugin (which wraps the Claude launch
# command when enabled). Installed into an isolated venv so it can't perturb system Python;
# [proxy] pulls the FastAPI/uvicorn server + core compressors (no torch/ML — too heavy for the
# sandbox, and the JSON/AST compressors deliver most of the savings).
RUN python3 -m venv /opt/headroom \
    && /opt/headroom/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/headroom/bin/pip install --no-cache-dir "headroom-ai[proxy,mcp]"
ENV PATH="/opt/headroom/bin:${PATH}"

# Globally install Claude Code. The agent runs as the unprivileged 'node' user,
# but the global npm prefix is root-owned, so the in-process auto-updater can't
# write there ("no write permission to npm prefix"). Disable it — the version is
# fixed at build time and updates happen by rebuilding the image.
ENV DISABLE_AUTOUPDATER=1
RUN npm install -g @anthropic-ai/claude-code

# Set up the workspace directory
WORKDIR /workspace

# Plugins. Every plugin ships in the image; ENABLE_<NAME> flags decide at container start which
# ones actually run (see run.sh), so changing the mix needs no rebuild. Permissions follow a
# convention: bin/ is world-executable (hooks run as the agent), root/ is root-only (secrets),
# and everything lands root-owned outside /workspace so the agent cannot edit its own guardrails.
COPY plugins /opt/plugins
RUN chown -R root:root /opt/plugins \
    && find /opt/plugins -type d -exec chmod 555 {} + \
    && find /opt/plugins -type f -exec chmod 444 {} + \
    && find /opt/plugins -type f -path '*/bin/*' -exec chmod 555 {} + \
    && find /opt/plugins -type f -path '*/root/*' -exec chmod 500 {} +

# Plugin framework: the shell library the boot scripts source, the settings merger, and the base
# policy that plugin settings.json fragments are merged into at runtime.
COPY src/lib/plugins.sh /usr/local/lib/sandbox/plugins.sh
COPY src/merge-settings.py /usr/local/bin/merge-settings.py
COPY settings-base.json /usr/local/share/sandbox/settings-base.json
RUN chmod 555 /usr/local/bin/merge-settings.py \
    && chmod 444 /usr/local/lib/sandbox/plugins.sh /usr/local/share/sandbox/settings-base.json

# Pre-seed Claude Code's config for the 'node' user, so it boots non-interactively (onboarding
# skipped, permissions warning accepted, /workspace pre-trusted). agent-setup.sh still merges
# those fields in at runtime, so this just saves that step from starting off an empty "{}".
COPY .claude.json /home/node/.claude.json
RUN chown node:node /home/node/.claude.json

# Create an entrypoint shell script to handle token generation and boot Claude.
# agent-setup.sh holds the sequence the entrypoint runs as the 'node' user; it
# lives in its own file so editors give it linting/highlighting.
COPY src/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY src/agent-setup.sh /usr/local/bin/agent-setup.sh
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/agent-setup.sh

# The container will run under the unprivileged 'node' user by default
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
