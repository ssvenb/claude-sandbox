FROM node:20-bookworm-slim

# Install automation dependencies and system utilities. Anything a single plugin owns is
# installed by that plugin's install.sh instead (see the plugin build stage below).
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

# Globally install Claude Code. The agent runs as the unprivileged 'node' user,
# but the global npm prefix is root-owned, so the in-process auto-updater can't
# write there ("no write permission to npm prefix"). Disable it — the version is
# fixed at build time and updates happen by rebuilding the image.
ENV DISABLE_AUTOUPDATER=1
RUN npm install -g @anthropic-ai/claude-code

# Set up the workspace directory
WORKDIR /workspace

# Plugins. Every plugin's files ship in the image; ENABLE_<NAME> flags decide which ones actually
# run (see run.sh) and which ones get their dependencies installed below. Permissions follow a
# convention: bin/ is world-executable (hooks run as the agent), root/ is root-only (secrets),
# and everything lands root-owned outside /workspace so the agent cannot edit its own guardrails.
COPY plugins /opt/plugins
# Only the plugins listed in ENABLED_PLUGINS get their dependencies installed, so a disabled
# plugin's binaries stay out of the image. Flipping ENABLE_<NAME> therefore needs a rebuild;
# run.sh passes the resolved list as a build arg. Empty means "install everything".
ARG ENABLED_PLUGINS=
RUN set -eu; for f in /opt/plugins/*/install.sh; do \
      [ -f "$f" ] || continue; \
      name=$(basename "$(dirname "$f")"); \
      if [ -n "$ENABLED_PLUGINS" ]; then \
        case " $ENABLED_PLUGINS " in *" $name "*) ;; *) echo "⏭️  $name (disabled)"; continue ;; esac; \
      fi; \
      echo "📦 $f"; sh "$f"; \
    done
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
