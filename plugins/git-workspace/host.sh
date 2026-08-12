# shellcheck shell=bash
# Host stage: nothing secret here, just the repo coordinates the agent stage needs.

pass_env REPO_URL
pass_value BASE_BRANCH "${BASE_BRANCH:-main}"
