# shellcheck shell=sh
# Agent stage. Make the service account's token — minted on the host, refreshed under
# /run/credentials — the container's ambient Google identity, the way a GCE VM has one:
#   client libraries  ask a stand-in metadata server (bin/metadata.py), found via GCE_METADATA_*
#   gcloud            reads the token file itself on every call (auth/access_token_file)

GCP_TOKEN_FILE=${GCP_TOKEN_FILE:-/run/credentials/gcp-token}
[ -s "$GCP_TOKEN_FILE" ] || { echo "❌ gcp-auth: $GCP_TOKEN_FILE is missing" >&2; exit 1; }

# A free port rather than a fixed one, so it never collides with one the agent's own work binds.
mkdir -p "$HOME/.cache"
GCP_METADATA_PORT=$("$PLUGIN_DIR/bin/metadata.py" --token-file "$GCP_TOKEN_FILE" \
  --account "$GCP_SERVICE_ACCOUNT" --project "$GCP_PROJECT" --log "$HOME/.cache/gcp-metadata.log")
export GCE_METADATA_HOST="127.0.0.1:$GCP_METADATA_PORT"
export GCE_METADATA_IP="$GCE_METADATA_HOST" GCE_METADATA_ROOT="$GCE_METADATA_HOST"

export CLOUDSDK_AUTH_ACCESS_TOKEN_FILE="$GCP_TOKEN_FILE"
export CLOUDSDK_CORE_PROJECT="$GCP_PROJECT" GOOGLE_CLOUD_PROJECT="$GCP_PROJECT"
# Unattended: no surveys, no usage-reporting prompt.
export CLOUDSDK_SURVEY_DISABLE_PROMPTS=1 CLOUDSDK_CORE_DISABLE_USAGE_REPORTING=true

echo "☁️  gcp-auth: $GCP_SERVICE_ACCOUNT via metadata server on $GCE_METADATA_HOST"
unset GCP_TOKEN_FILE GCP_METADATA_PORT

# Tell the agent it already has a Google Cloud identity, so it uses it as is instead of hunting for
# a key file or trying to log in.

{
  printf '\n## Google Cloud\n\n'
  printf 'You are authenticated to Google Cloud as the service account `%s` (project `%s`). ' \
    "$GCP_SERVICE_ACCOUNT" "$GCP_PROJECT"
  printf '`gcloud` and the Google client libraries pick this identity up on their own — as on a GCE '
  printf 'VM, through a metadata server at %s — so do not run `gcloud auth login`, create ' "$GCE_METADATA_HOST"
  printf 'service account keys, or set GOOGLE_APPLICATION_CREDENTIALS. Short-lived tokens are '
  printf 'renewed automatically. What you may do is limited to the service account'"'"'s IAM roles; a '
  printf '403 from Google means the sandbox is not meant to have that access.\n'
} >> "$AGENT_PROMPT_FILE"
