# shellcheck shell=bash
# Per-project settings. Sourced by run.sh (bash, on YOUR machine).
#
# Everything in the sandbox's .env can be overridden per project, so a checkout carries the way it
# wants to be sandboxed. Lowest to highest precedence:
#
#   1. a plugin manifest's defaultEnabled, and each setting's built-in default
#   2. the sandbox's .env (or anything already exported in your shell)
#   3. the worked-on repo's .env               — sandbox-owned keys only
#   4. the worked-on repo's .claude-sandbox.json — "env" block, and per-plugin "enabled"
#
# Layer 3 is filtered because that file is the target repo's, full of its own secrets: only names
# the sandbox owns are lifted out of it, so a stray pass_env cannot forward the repo's API keys
# into the container. "Owned" is every key in .env.example plus any ENABLE_<PLUGIN> flag.

SANDBOX_ENV_EXAMPLE="${SANDBOX_ENV_EXAMPLE:-.env.example}"
declare -A SANDBOX_VARS=()

sandbox_vars_load() { env_scan_into SANDBOX_VARS "$SANDBOX_ENV_EXAMPLE" commented; }

# Is NAME a setting the sandbox owns, rather than one of the worked-on repo's own variables?
sandbox_owns_var() {
  case "$1" in ENABLE_*) return 0 ;; esac
  [ -n "${SANDBOX_VARS[$1]+x}" ]
}

# Apply layers 3 and 4 over the environment, before the agent and the plugins are resolved.
project_settings_apply() {
  local key value applied=()

  sandbox_vars_load

  for key in "${!PROJECT_ENV[@]}"; do
    sandbox_owns_var "$key" || continue
    export "$key=${PROJECT_ENV[$key]}"
    applied+=("$key")
  done

  if [ -n "$PROJECT_CONFIG_JSON" ]; then
    while IFS=$'\t' read -r key value; do
      [ -n "$key" ] || continue
      # This block is written *for* the sandbox, so an unknown name is a typo, not one of the
      # repo's own variables — say so instead of silently ignoring it.
      sandbox_owns_var "$key" \
        || die "Project config '$PROJECT_CONFIG_FILE': .env.$key is not a sandbox setting (see .env.example)."
      export "$key=$value"
      applied+=("$key")
    done < <(printf '%s' "$PROJECT_CONFIG_JSON" | jq -r '(.env // {}) | to_entries[] | "\(.key)\t\(.value)"')
  fi

  [ ${#applied[@]} -gt 0 ] \
    && echo "⚙️  Project settings: $(printf '%s\n' "${applied[@]}" | sort -u | paste -sd' ' -)"
  return 0
}
