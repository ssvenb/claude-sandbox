# shellcheck shell=bash
# Web stage: a pull request on one of this plugin's per-run branches, <prefix>/<yyyymmdd>-<RUN_ID>,
# belongs to that run — which is what lets the page offer to resume it. Runs after the plugin that
# listed the pull requests (priority), and marks whatever item carries such a `branch`.

web_map_items 'if (.branch // "") | test("^.+/[0-9]{8}-[0-9a-f]{6}$") then .run_id = .branch[-6:] else . end'
