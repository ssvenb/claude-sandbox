# shellcheck shell=sh
# Agent stage. Say which files were masked, so the agent does not waste a turn on an "empty" file.

[ -n "${CWD_WORKSPACE_HIDDEN:-}" ] || return 0

{
  printf '\n## Masked files\n\n'
  printf 'These files exist on the host but are deliberately masked in here and read as empty:\n\n'
  for path in $CWD_WORKSPACE_HIDDEN; do
    printf -- '- `%s`\n' "$path"
  done
  printf '\nThey usually hold credentials. Do not try to read, recreate, or write them — treat '
  printf 'them as present and correct outside the sandbox.\n'
} >> "$AGENT_PROMPT_FILE"
