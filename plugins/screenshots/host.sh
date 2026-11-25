# shellcheck shell=bash
# Host stage: mount the host's screenshot folder read-only where the agent will look for it.
_dir="${SCREENSHOTS_DIR:-$HOME/Pictures/Screenshots}"
[ -d "$_dir" ] || die "screenshots: no such directory: $_dir (set the plugin's directory, or switch it off, in the project's settings)"
pass_mount "$_dir" /home/node/Pictures/Screenshots ro
unset _dir
