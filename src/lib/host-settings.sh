# shellcheck shell=bash
# Per-project settings. Sourced by run.sh (bash, on YOUR machine).
#
# The sandbox's own .env holds your defaults — the ones that are the same whatever repo you point
# it at. Everything in it can be overridden per project, so a checkout carries the way it wants to
# be sandboxed: which agent, which plugins, which directories. Lowest to highest precedence:
#
#   1. a plugin manifest's defaultEnabled, and each setting's built-in default
#   2. the sandbox's .env (or anything already exported in your shell)
#   3. the worked-on repo's .env               — sandbox-owned keys only, see below
#   4. the worked-on repo's .claude-sandbox.json — "env" block, and per-plugin "enabled"
#
# Layer 3 is the delicate one: that file is the target repo's, full of its own secrets, so only
# the names the sandbox itself owns are lifted out of it. Everything else stays in the array
# project_env() reads and never becomes an environment variable here — a stray pass_env in some
# plugin must not be able to forward the repo's API keys into the container.
#
# "Owned" is defined by .env.example, which every sandbox variable must appear in anyway, plus
# any ENABLE_<PLUGIN> flag (those are generated from the plugin directory names).

SANDBOX_ENV_EXAMPLE="${SANDBOX_ENV_EXAMPLE:-.env.example}"
declare -A SANDBOX_VARS=()

sandbox_vars_load() {
  local line key
  [ -f "$SANDBOX_ENV_EXAMPLE" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    line=${line%$'\r'}
    line=${line#"${line%%[![:space:]]*}"}
    line=${line#\#}                      # documented-but-commented defaults count too
    line=${line#"${line%%[![:space:]]*}"}
    key=${line%%=*}
    case "$line" in *=*) ;; *) continue ;; esac
    case "$key" in [A-Za-z_]*) ;; *) continue ;; esac
    case "$key" in *[!A-Za-z0-9_]*) continue ;; esac   # prose that happens to contain '='
    SANDBOX_VARS["$key"]=1
  done <"$SANDBOX_ENV_EXAMPLE"
}

# Is NAME a setting the sandbox owns, rather than one of the worked-on repo's own variables?
sandbox_owns_var() {
  case "$1" in ENABLE_*) return 0 ;; esac
  [ -n "${SANDBOX_VARS[$1]:-}" ]
}

# Apply layers 3 and 4 over the environment. Runs before the agent and the plugins are resolved,
# so what it sets is what the rest of the run sees.
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
      # This block is written *for* the sandbox, so a name it does not know is a typo, not one of
      # the repo's own variables — say so instead of silently ignoring it.
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
