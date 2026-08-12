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

# Headroom compression proxy. Claude Code's LLM calls are routed THROUGH this proxy (see
# agent-setup.sh: `headroom wrap claude`), which compresses tool outputs / context before
# they reach the Anthropic API and transparently forwards Claude's own auth upstream.
# Installed into an isolated venv so it can't perturb system Python; [proxy] pulls the
# FastAPI/uvicorn server + core compressors (no torch/ML — too heavy for the sandbox, and
# the JSON/AST compressors deliver most of the savings). Telemetry off: the agent's traffic
# must not leave the box (data-residency).
ENV HEADROOM_TELEMETRY=off
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

# Branch guard: PreToolUse hook + managed (enterprise) policy that enables it.
# Both land as root-owned files outside /workspace, so the unprivileged 'node'
# user the agent runs as cannot edit or disable them.
COPY guard-branch.py /usr/local/bin/guard-branch.py
COPY managed-settings.json /etc/claude-code/managed-settings.json
RUN chmod 555 /usr/local/bin/guard-branch.py \
    && chmod 444 /etc/claude-code/managed-settings.json

# mint-gh-token.py mints GitHub App installation tokens and is run by root only.
# chmod 500 (root-owned) keeps the unprivileged 'node' user from reading or
# executing it — defense in depth; node never holds the App key env vars anyway.
COPY mint-gh-token.py /usr/local/bin/mint-gh-token.py
RUN chmod 500 /usr/local/bin/mint-gh-token.py

# Create an entrypoint shell script to handle token generation and boot Claude.
# agent-setup.sh holds the sequence the entrypoint runs as the 'node' user; it
# lives in its own file so editors give it linting/highlighting.
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY agent-setup.sh /usr/local/bin/agent-setup.sh
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/agent-setup.sh

# The container will run under the unprivileged 'node' user by default
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
