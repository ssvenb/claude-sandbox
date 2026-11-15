# shellcheck shell=bash
# Web stage: a review session for each pull request that is ready for one. Runs after github-auth
# listed the open pull requests with their CI and head commit, and git-workspace tied each to the
# run whose branch it is on. Ready is: of a sandbox run, not a draft, CI green — and that run's
# session gone from the page (web_start's `after_run`): while it is listed, its work is not over.
# Once per head commit, so a push after a rejected review is reviewed again.

pr_review_auth=$(plugin_config '.auth')
if [ -z "$pr_review_auth" ]; then
  web_note "pr-review: no reviewer authentication set (.plugins[\"pr-review\"].auth), so nothing is reviewed"
  return 0
fi
if [ "$pr_review_auth" = "${GH_AUTH:-}" ]; then
  web_note "pr-review: the reviewer authentication is the one the pull requests are opened with; GitHub lets nobody approve their own"
  return 0
fi
pr_review_prompt=$(plugin_config '.prompt' "$(jq -r '.settings[] | select(.key == "prompt").default' "$PLUGIN_DIR/plugin.json")")

# Only the number, the address and the commit go into the task: a title is the author's text.
while IFS= read -r pr_review_start; do
  web_start "$pr_review_start"
done < <(jq -c --arg auth "$pr_review_auth" --arg prompt "$pr_review_prompt" '.run_items[]
  | select(.section == "Pull requests" and .status == "ok" and .note != "Draft"
           and (.run_id // "") != "" and (.sha // "") != "")
  | {key: "\(.ref)@\(.sha)", after_run: .run_id, env: {GH_AUTH: $auth},
     task: "\($prompt)\n\nThe pull request to review is \(.ref): \(.url)\nThe commit to review is \(.sha)."}' <<<"$WEB_JSON")
unset pr_review_auth pr_review_prompt pr_review_start
