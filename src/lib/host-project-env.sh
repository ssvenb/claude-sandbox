# shellcheck shell=bash
# The worked-on repo's .env. Sourced by run.sh (bash, on YOUR machine).
#
# Some settings belong to the repo the agent works on rather than to the sandbox, and a repo
# conventionally keeps them in its own .env — BRANCH_PREFIX, say. That file is the target repo's:
# it is full of its own secrets and possibly its own commands, so it is *scanned*, never sourced.
# The assignments land in an array only this file reads, and a plugin asks for the one key it
# wants with `project_env`. Nothing here reaches the container except through a plugin's own
# pass_* calls.
#
#   PROJECT_ENV_FILE   override the path (default: $HOST_CWD/.env; /dev/null loads nothing)

PROJECT_ENV_FILE="${PROJECT_ENV_FILE:-${HOST_CWD:-$PWD}/.env}"
declare -A PROJECT_ENV=()

project_env_load() {
  local line key value
  [ -n "$PROJECT_ENV_FILE" ] && [ -f "$PROJECT_ENV_FILE" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    line=${line%$'\r'}                                        # CRLF checkouts
    line=${line#"${line%%[![:space:]]*}"}                      # leading blanks
    case "$line" in ''|'#'*) continue ;; esac
    line=${line#export}
    line=${line#"${line%%[![:space:]]*}"}
    case "$line" in *=*) ;; *) continue ;; esac
    key=${line%%=*}
    key=${key%"${key##*[![:space:]]}"}                         # trailing blanks
    case "$key" in [A-Za-z_]*) ;; *) continue ;; esac
    case "$key" in *[!A-Za-z0-9_]*) continue ;; esac
    value=${line#*=}
    value=${value#"${value%%[![:space:]]*}"}
    value=${value%"${value##*[![:space:]]}"}
    case "$value" in
      \"*\") value=${value#\"}; value=${value%\"} ;;
      \'*\') value=${value#\'}; value=${value%\'} ;;
    esac
    PROJECT_ENV["$key"]=$value                                 # last assignment wins
  done <"$PROJECT_ENV_FILE"
}

# project_env <NAME> [default] — the value that file assigns to NAME, else the default.
project_env() {
  printf '%s' "${PROJECT_ENV[$1]:-${2-}}"
}
