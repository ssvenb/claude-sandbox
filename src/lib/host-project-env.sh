# shellcheck shell=bash
# The worked-on repo's .env. Sourced by run.sh (bash, on YOUR machine).
#
# Settings that belong to the repo rather than to the sandbox (BRANCH_PREFIX, say) conventionally
# live in its own .env. That file is the target repo's — full of its own secrets and possibly its
# own commands — so it is *scanned*, never sourced. A plugin asks for the one key it wants with
# `project_env`; nothing here reaches the container except through a plugin's own pass_* calls.
#
#   PROJECT_ENV_FILE   override the path (default: $HOST_CWD/.env; /dev/null loads nothing)

PROJECT_ENV_FILE="${PROJECT_ENV_FILE:-${HOST_CWD:-$PWD}/.env}"
declare -A PROJECT_ENV=()

# env_scan_into <assoc-array> <file> [commented] — parse KEY=VALUE lines into the named array.
# With "commented", `#KEY=value` counts too, which is how .env.example documents optional
# defaults; without it, comments are skipped.
env_scan_into() {
  local -n _env_out=$1
  local file=$2 commented=${3:-} line key value
  [ -n "$file" ] && [ -f "$file" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    line=${line%$'\r'}                                         # CRLF checkouts
    line=${line#"${line%%[![:space:]]*}"}                       # leading blanks
    if [ -n "$commented" ]; then
      line=${line#\#}
      line=${line#"${line%%[![:space:]]*}"}
    else
      case "$line" in ''|'#'*) continue ;; esac
    fi
    line=${line#export}
    line=${line#"${line%%[![:space:]]*}"}
    case "$line" in *=*) ;; *) continue ;; esac
    key=${line%%=*}
    key=${key%"${key##*[![:space:]]}"}                          # trailing blanks
    case "$key" in [A-Za-z_]*) ;; *) continue ;; esac
    case "$key" in *[!A-Za-z0-9_]*) continue ;; esac            # prose that contains '='
    value=${line#*=}
    value=${value#"${value%%[![:space:]]*}"}
    value=${value%"${value##*[![:space:]]}"}
    case "$value" in
      \"*\") value=${value#\"}; value=${value%\"} ;;
      \'*\') value=${value#\'}; value=${value%\'} ;;
    esac
    _env_out["$key"]=$value                                     # last assignment wins
  done <"$file"
}

project_env_load() { env_scan_into PROJECT_ENV "$PROJECT_ENV_FILE"; }

# project_env <NAME> [default] — the value that file assigns to NAME, else the default.
project_env() {
  printf '%s' "${PROJECT_ENV[$1]:-${2-}}"
}
