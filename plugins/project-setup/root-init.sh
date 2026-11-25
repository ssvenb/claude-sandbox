# shellcheck shell=sh
# Root stage: point browser tooling at what install.sh built in. The exports survive the handoff to
# the agent user.
if [ -x /usr/bin/chromium ]; then
  export CHROME_BIN=/usr/bin/chromium PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium PUPPETEER_SKIP_DOWNLOAD=1
fi
if [ -d /ms-playwright ]; then
  # The agent's user may have taken the host user's uid (entrypoint.sh): the shared browser path
  # follows it, so a project pinning another Playwright release can still install its build there.
  find /ms-playwright -xdev ! -user node -exec chown -h node {} +
  export PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
fi
