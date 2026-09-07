FROM node:20-bookworm-slim

# Shared dependencies only; anything a single plugin needs is installed by its own install.sh.
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

# Every agent's files ship in the image, but only the one named by AGENT gets its CLI installed.
# AGENT_VERSION (resolved on the host, empty means latest) is part of this layer's cache key, so
# the layer rebuilds exactly when a new release is out; it is referenced in the RUN so the value
# cannot be optimised away.
COPY agents /opt/agents
ARG AGENT=claude
ARG AGENT_VERSION=
RUN set -eu; \
    [ -d "/opt/agents/$AGENT" ] || { echo "Unknown agent: $AGENT" >&2; exit 1; }; \
    if [ -f "/opt/agents/$AGENT/install.sh" ]; then \
      echo "🤖 $AGENT ${AGENT_VERSION:-latest}"; \
      AGENT_VERSION="$AGENT_VERSION" sh "/opt/agents/$AGENT/install.sh"; \
    fi
RUN chown -R root:root /opt/agents \
    && find /opt/agents -type d -exec chmod 555 {} + \
    && find /opt/agents -type f -exec chmod 444 {} +

WORKDIR /workspace

# Every plugin's files ship in the image; only those in ENABLED_PLUGINS (resolved by run.sh, empty
# means all) get their dependencies installed, so flipping a flag rebuilds from here.
COPY plugins /opt/plugins
ARG ENABLED_PLUGINS=
RUN set -eu; for f in /opt/plugins/*/install.sh; do \
      [ -f "$f" ] || continue; \
      name=$(basename "$(dirname "$f")"); \
      if [ -n "$ENABLED_PLUGINS" ]; then \
        case " $ENABLED_PLUGINS " in *" $name "*) ;; *) echo "⏭️  $name (disabled)"; continue ;; esac; \
      fi; \
      echo "📦 $f"; sh "$f"; \
    done
# bin/ is world-executable (hooks run as the agent), root/ is root-only (secrets), and everything
# lands root-owned outside /workspace so the agent cannot edit its own guardrails.
RUN chown -R root:root /opt/plugins \
    && find /opt/plugins -type d -exec chmod 555 {} + \
    && find /opt/plugins -type f -exec chmod 444 {} + \
    && find /opt/plugins -type f -path '*/bin/*' -exec chmod 555 {} + \
    && find /opt/plugins -type f -path '*/root/*' -exec chmod 500 {} +

# The frameworks the boot scripts source, the settings merger, and the base policy the plugin
# settings.json fragments are merged into at runtime.
COPY src/lib/plugins.sh /usr/local/lib/sandbox/plugins.sh
COPY src/lib/agents.sh /usr/local/lib/sandbox/agents.sh
COPY src/merge-settings.py /usr/local/bin/merge-settings.py
COPY settings-base.json /usr/local/share/sandbox/settings-base.json
RUN chmod 555 /usr/local/bin/merge-settings.py \
    && chmod 444 /usr/local/lib/sandbox/plugins.sh /usr/local/lib/sandbox/agents.sh \
                 /usr/local/share/sandbox/settings-base.json

# entrypoint.sh boots as root; agent-setup.sh is the part it runs as 'node'.
COPY src/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY src/agent-setup.sh /usr/local/bin/agent-setup.sh
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/agent-setup.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
