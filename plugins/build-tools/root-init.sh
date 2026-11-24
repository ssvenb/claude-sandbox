# shellcheck shell=sh
# Root stage: point browser tooling at what install.sh built in. The exports survive the handoff to
# the agent user.
if [ -x /usr/bin/chromium ]; then
  export CHROME_BIN=/usr/bin/chromium PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium PUPPETEER_SKIP_DOWNLOAD=1
fi
[ -d /ms-playwright ] && export PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
true
