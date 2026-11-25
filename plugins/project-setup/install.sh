#!/bin/sh
# Build-time install (root, during docker build): the recipes in $BUILD_TOOLS, then the packages in
# $BUILD_TOOLS_APT / _NPM / _PIP. All are build args (see host.sh and the Dockerfile's defaults).
# The lists hold names validated on the host and are expanded unquoted; -f keeps ruff==0.6.* a name.
set -euf

apt_install() {
  apt-get update
  apt-get install -y --no-install-recommends "$@"
  rm -rf /var/lib/apt/lists/*
}

for tool in ${BUILD_TOOLS:-}; do
  echo "🔧 project-setup: $tool"
  case "$tool" in
    python-pip) apt_install python3-pip python3-venv ;;
    terraform)
      curl -fsSL https://apt.releases.hashicorp.com/gpg \
        | gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
      echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(. /etc/os-release && echo "$VERSION_CODENAME") main" \
        > /etc/apt/sources.list.d/hashicorp.list
      apt_install terraform ;;
    # Debian has no package; the PyPI wheel is one static binary.
    ruff)
      command -v pip3 >/dev/null || apt_install python3-pip
      pip3 install --no-cache-dir --break-system-packages ruff ;;
    # Docker has no user namespaces for Chromium's sandbox and a 64 MB /dev/shm, so the Debian
    # wrapper always adds the flags that work around both. root-init.sh points Puppeteer at it.
    chromium)
      apt_install chromium fonts-liberation
      echo 'export CHROMIUM_FLAGS="$CHROMIUM_FLAGS --no-sandbox --disable-dev-shm-usage"' \
        > /etc/chromium.d/sandbox ;;
    # Playwright's own Chromium, because a project's @playwright/test only runs the exact build it
    # pins. Shared path, owned by node so a project pinning another release can install its build too.
    playwright)
      PLAYWRIGHT_BROWSERS_PATH=/ms-playwright npx -y playwright@latest install --with-deps chromium
      chown -R node:node /ms-playwright
      rm -rf /var/lib/apt/lists/* /root/.npm ;;
    *) echo "Unknown build tool: $tool" >&2; exit 1 ;;
  esac
done

# shellcheck disable=SC2086  # package names, validated on the host
[ -z "${BUILD_TOOLS_APT:-}" ] || apt_install $BUILD_TOOLS_APT
# shellcheck disable=SC2086
[ -z "${BUILD_TOOLS_NPM:-}" ] || { npm install -g $BUILD_TOOLS_NPM && rm -rf /root/.npm; }
if [ -n "${BUILD_TOOLS_PIP:-}" ]; then
  command -v pip3 >/dev/null || apt_install python3-pip
  # PEP 668: Debian's python is externally managed, but this is a throwaway image.
  # shellcheck disable=SC2086
  pip3 install --no-cache-dir --break-system-packages $BUILD_TOOLS_PIP
fi
