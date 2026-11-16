# shellcheck shell=bash
# Host stage: tells the container when this run is a review the plugin started itself (web.sh),
# which is when its agent-init.sh hands the agent the reviewer's guardrails.

if [ "${SANDBOX_STARTED_BY:-}" = pr-review ]; then
  pass_value PR_REVIEW 1
fi
