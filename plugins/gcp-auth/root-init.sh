# shellcheck shell=sh
# Root stage. Make the service account's token — minted on the host, refreshed under
# /run/credentials — the container's ambient Google identity, the way a GCE VM has one:
#   client libraries  ask a stand-in metadata server (root/metadata.py), found via GCE_METADATA_*
#   gcloud            reads the token file itself on every call (auth/access_token_file)
# Nothing here is secret, but the metadata server runs as root so the agent cannot replace it.

GCP_TOKEN_FILE=/run/credentials/gcp-token
[ -s "$GCP_TOKEN_FILE" ] || { echo "❌ gcp-auth: $GCP_TOKEN_FILE is missing" >&2; exit 1; }

# A free port rather than a fixed one: under host-network the loopback is shared by every sandbox.
GCP_METADATA_PORT=$("$PLUGIN_DIR/root/metadata.py" --token-file "$GCP_TOKEN_FILE" \
  --account "$GCP_SERVICE_ACCOUNT" --project "$GCP_PROJECT" --log /var/log/gcp-metadata.log)
export GCE_METADATA_HOST="127.0.0.1:$GCP_METADATA_PORT"
export GCE_METADATA_IP="$GCE_METADATA_HOST" GCE_METADATA_ROOT="$GCE_METADATA_HOST"

export CLOUDSDK_AUTH_ACCESS_TOKEN_FILE="$GCP_TOKEN_FILE"
export CLOUDSDK_CORE_PROJECT="$GCP_PROJECT" GOOGLE_CLOUD_PROJECT="$GCP_PROJECT"
# Unattended: no surveys, no usage-reporting prompt.
export CLOUDSDK_SURVEY_DISABLE_PROMPTS=1 CLOUDSDK_CORE_DISABLE_USAGE_REPORTING=true

echo "☁️  gcp-auth: $GCP_SERVICE_ACCOUNT via metadata server on $GCE_METADATA_HOST"
unset GCP_TOKEN_FILE GCP_METADATA_PORT
