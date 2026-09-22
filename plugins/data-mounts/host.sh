# shellcheck shell=bash
# Host stage: mount whatever the worked-on repo lists in
#   .plugins["data-mounts"].mounts = ["/host/path:/container/path[:ro]", ...]
# A bare path ("~/data.duckdb") is mounted at that same absolute path in the container;
# relative host paths resolve against the worked-on repo. No list → nothing happens.
while IFS= read -r spec; do
  [ -n "$spec" ] || continue
  IFS=: read -r host_path container_path opts <<<"$spec"
  host_path="${host_path/#\~/$HOME}"
  case $host_path in /*) ;; *) host_path="$HOST_CWD/$host_path" ;; esac
  [ -e "$host_path" ] || die "data-mounts: no such host path: $host_path"
  host_path="$(cd "$(dirname "$host_path")" && pwd)/$(basename "$host_path")"
  container_path="${container_path:-$host_path}"
  [ "${container_path:0:1}" = / ] || die "data-mounts: container path must be absolute: $spec"
  pass_mount "$host_path" "$container_path" ${opts:+$opts}
  echo "📁 data-mounts: $host_path → $container_path${opts:+ ($opts)}"
done < <(plugin_config_json '.mounts // []' '[]' | jq -r '.[]')
