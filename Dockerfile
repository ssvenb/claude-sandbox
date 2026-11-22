# Only the install scripts, so the dependency layers below are keyed on them alone: editing any
# other agent or plugin file reuses them instead of reinstalling everything.
FROM node:20-bookworm-slim AS installers
COPY agents /i/agents
COPY plugins /i/plugins
RUN find /i -type f ! -name install.sh -delete

FROM node:20-bookworm-slim

# Shared dependencies only; anything a single plugin needs is installed by its own install.sh.
RUN apt-get update && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        wget \
        gnupg \
        jq \
        openssl \
        git \
        python3 \
        python3-venv \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Extra root CAs from the ca-certs plugin (PEM, empty when it is off), so HTTPS during the build
# works behind a TLS-intercepting proxy too. The ENV points Node and Python at the system store,
# which is a superset of their own bundles.
ARG EXTRA_CA_CERTS=
RUN if [ -n "$EXTRA_CA_CERTS" ]; then \
      printf '%s\n' "$EXTRA_CA_CERTS" > /usr/local/share/ca-certificates/sandbox-extra.crt \
      && update-ca-certificates; \
    fi
ENV NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# Terraform, from HashiCorp's apt repository.
RUN curl -fsSL https://apt.releases.hashicorp.com/gpg \
        | gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(. /etc/os-release && echo "$VERSION_CODENAME") main" \
        > /etc/apt/sources.list.d/hashicorp.list \
    && apt-get update && apt-get install -y --no-install-recommends terraform \
    && rm -rf /var/lib/apt/lists/*

# Ruff, Python's linter and formatter. Debian has no package; the PyPI wheel is one static binary.
RUN pip3 install --no-cache-dir --break-system-packages ruff

# Headless Chromium, from Debian's repository. Docker has no user namespaces for its sandbox and a
# 64 MB /dev/shm, so the Debian wrapper always adds the flags that work around both; Puppeteer is
# pointed at it instead of downloading its own browser.
RUN apt-get update && apt-get install -y --no-install-recommends chromium fonts-liberation \
    && rm -rf /var/lib/apt/lists/* \
    && echo 'export CHROMIUM_FLAGS="$CHROMIUM_FLAGS --no-sandbox --disable-dev-shm-usage"' \
        > /etc/chromium.d/sandbox
ENV CHROME_BIN=/usr/bin/chromium \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium \
    PUPPETEER_SKIP_DOWNLOAD=1

# Playwright's own Chromium, because a project's @playwright/test only runs the exact build it
# pins, not Debian's. Shared path, owned by node so a project pinning another Playwright release
# can still `npx playwright install chromium` its build next to this one.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN npx -y playwright@latest install --with-deps chromium \
    && chown -R node:node /ms-playwright \
    && rm -rf /var/lib/apt/lists/* /root/.npm

# Plugin dependencies first: they change far less often than the agent CLI's version. Only those
# in ENABLED_PLUGINS (resolved by run.sh, empty means all) get installed, so flipping a flag
# rebuilds from here.
ARG ENABLED_PLUGINS=
RUN --mount=type=bind,from=installers,source=/i/plugins,target=/tmp/plugins \
    set -eu; for f in /tmp/plugins/*/install.sh; do \
      [ -f "$f" ] || continue; \
      name=$(basename "$(dirname "$f")"); \
      if [ -n "$ENABLED_PLUGINS" ]; then \
        case " $ENABLED_PLUGINS " in *" $name "*) ;; *) echo "⏭️  $name (disabled)"; continue ;; esac; \
      fi; \
      echo "📦 $name"; sh "$f"; \
    done

# Only the agent named by AGENT gets its CLI installed. AGENT_VERSION (resolved on the host, empty
# means latest) is part of this layer's cache key, so the layer rebuilds exactly when a new release
# is out; it is referenced in the RUN so the value cannot be optimised away.
ARG AGENT=claude
ARG AGENT_VERSION=
RUN --mount=type=bind,from=installers,source=/i/agents,target=/tmp/agents \
    set -eu; \
    [ -d "/tmp/agents/$AGENT" ] || { echo "Unknown agent: $AGENT" >&2; exit 1; }; \
    if [ -f "/tmp/agents/$AGENT/install.sh" ]; then \
      echo "🤖 $AGENT ${AGENT_VERSION:-latest}"; \
      AGENT_VERSION="$AGENT_VERSION" sh "/tmp/agents/$AGENT/install.sh"; \
    fi

WORKDIR /workspace

# Every agent's and plugin's files ship in the image.
COPY agents /opt/agents
RUN chown -R root:root /opt/agents \
    && find /opt/agents -type d -exec chmod 555 {} + \
    && find /opt/agents -type f -exec chmod 444 {} +
COPY plugins /opt/plugins
# bin/ is world-executable (the agent runs it: hooks, helpers), and everything lands root-owned
# outside /workspace, so the agent does not edit its guardrails by accident. Guardrails only: the
# agent is root here whenever it wants (the docker group), so nothing in the image is a boundary.
RUN chown -R root:root /opt/plugins \
    && find /opt/plugins -type d -exec chmod 555 {} + \
    && find /opt/plugins -type f -exec chmod 444 {} + \
    && find /opt/plugins -type f -path '*/bin/*' -exec chmod 555 {} +

# The frameworks the boot scripts source, the settings merger, and the base policy the plugin settings.json fragments are merged into at runtime.
COPY src/contract/container/plugins.sh /usr/local/lib/sandbox/plugins.sh
COPY src/contract/container/agents.sh /usr/local/lib/sandbox/agents.sh
# What the agents' chat bridges (agents/<name>/chat.mjs) share: the wire to the web UI.
COPY src/services/chat/chat-bridge.mjs /usr/local/lib/sandbox/chat-bridge.mjs
COPY src/services/settings/merge-settings.py /usr/local/bin/merge-settings.py
COPY src/services/settings/settings-base.json /usr/local/share/sandbox/settings-base.json
RUN chmod 555 /usr/local/bin/merge-settings.py \
    && chmod 444 /usr/local/lib/sandbox/plugins.sh /usr/local/lib/sandbox/agents.sh \
                 /usr/local/lib/sandbox/chat-bridge.mjs \
                 /usr/local/share/sandbox/settings-base.json

# entrypoint.sh boots as root; agent-setup.sh is the part it runs as 'node'.
COPY src/boot/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY src/boot/agent-setup.sh /usr/local/bin/agent-setup.sh
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/agent-setup.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
