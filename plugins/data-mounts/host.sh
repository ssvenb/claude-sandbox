# shellcheck shell=bash
# Host stage: give the project one persistent data directory, the same one every session:
#   ${XDG_DATA_HOME:-~/.local/share}/claude-sandbox/data/<project>  →  /data
# <project> is the project file's name (`--project my-app` → my-app), else the repo's name.
# Read-write unless the project sets .plugins["data-mounts"].readOnly = true.
project=$(basename "${PROJECT_CONFIG_FILE:-${HOST_CWD:-${REPO_URL:-repo}}}")
project=${project%.json}; project=${project%.git}
case $project in ''|.|..) die "data-mounts: cannot name a data directory after '$project'" ;; esac
data_dir="${XDG_DATA_HOME:-$HOME/.local/share}/claude-sandbox/data/$project"
mkdir -p "$data_dir"
if [ "$(plugin_config '.readOnly' false)" = true ]; then mode=ro; else mode=rw; fi
pass_mount "$data_dir" /data "$mode"
echo "📁 data-mounts: $data_dir → /data ($mode)"
