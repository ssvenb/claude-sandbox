# shellcheck shell=bash
# A .env file, scanned. Sourced by src/contract/host/stage.sh (bash, on YOUR machine).
#
# The sandbox takes no setting from a .env: a project's are in its .claude-sandbox.json. What is
# left is this parser, for a plugin that reads a file of the repo's for values, not settings
# (upstream-proxy's envFile: the secrets its routes inject). Such a file is the target repo's —
# full of its own secrets and possibly its own commands — so it is *scanned*, never sourced.
# src/orchestrator/config.py reads .env.example, the catalogue of the sandbox's names, by the same rules.

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
