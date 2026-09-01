# shellcheck shell=sh
# Root stage: install the packages the project asked for. Runs as root because apt, global npm
# and system pip all write outside the agent user's home — and at boot rather than at image build
# time, because the list belongs to the repo being worked on, not to the image (the same image
# serves every project).
#
# Only package NAMES arrive here, validated on the host against a strict character set, so the
# unquoted expansions below cannot turn into a second command. Project-supplied shell runs in
# agent-init.sh instead, unprivileged and after the secrets are dropped.

if [ -n "${PROJECT_DEPS_APT:-}" ]; then
  echo "📦 project-deps: apt-get install $PROJECT_DEPS_APT"
  apt-get update >/dev/null \
    && apt-get install -y --no-install-recommends $PROJECT_DEPS_APT \
    || echo "⚠️  project-deps: apt install failed ($PROJECT_DEPS_APT)" >&2
  rm -rf /var/lib/apt/lists/*
fi

if [ -n "${PROJECT_DEPS_NPM:-}" ]; then
  echo "📦 project-deps: npm install -g $PROJECT_DEPS_NPM"
  npm install -g $PROJECT_DEPS_NPM \
    || echo "⚠️  project-deps: npm install failed ($PROJECT_DEPS_NPM)" >&2
fi

if [ -n "${PROJECT_DEPS_PIP:-}" ]; then
  # Debian marks its python as externally managed (PEP 668); this is a throwaway container, so
  # installing into the system interpreter is the simplest thing that works.
  echo "📦 project-deps: pip install $PROJECT_DEPS_PIP"
  pip3 install --no-cache-dir --break-system-packages $PROJECT_DEPS_PIP \
    || echo "⚠️  project-deps: pip install failed ($PROJECT_DEPS_PIP)" >&2
fi
