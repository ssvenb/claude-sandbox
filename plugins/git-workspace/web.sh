# shellcheck shell=bash
# Web stage: a pull request on one of this plugin's per-run branches, <prefix>/<yyyymmdd>-<RUN_ID>,
# belongs to that run — so the page shows it, with its CI, on that run's session row, and offers
# to resume the run when no session of it is listed. Runs after the plugin that listed the pull
# requests (priority), and ties whatever item carries such a `branch`.

web_tie_items 'if (.branch // "") | test("^.+/[0-9]{8}-[0-9a-f]{6}$") then .branch[-6:] else null end'
