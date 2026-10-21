# shellcheck shell=bash
# Host stage. Your gcloud login stays on this machine: it mints 1-hour tokens for the service
# account, and the container only ever sees the current one, as /run/credentials/gcp-token. What
# the agent can do is exactly what that service account's IAM roles allow — scope it accordingly.

command -v gcloud >/dev/null || die "gcp-auth: gcloud is required on the host to mint tokens for $GCP_SERVICE_ACCOUNT."
[[ $GCP_SERVICE_ACCOUNT =~ ^[^@[:space:]]+@[^@[:space:]]+\.gserviceaccount\.com$ ]] \
  || die "gcp-auth: GCP_SERVICE_ACCOUNT must be a service account email (…@….iam.gserviceaccount.com), got '$GCP_SERVICE_ACCOUNT'."

# A user-managed service account's email names its project; anything else needs GCP_PROJECT.
GCP_AUTH_PROJECT=${GCP_PROJECT:-}
if [ -z "$GCP_AUTH_PROJECT" ] && [[ $GCP_SERVICE_ACCOUNT =~ @([a-z0-9-]+)\.iam\.gserviceaccount\.com$ ]]; then
  GCP_AUTH_PROJECT=${BASH_REMATCH[1]}
fi
[ -n "$GCP_AUTH_PROJECT" ] || die "gcp-auth: cannot tell the project from '$GCP_SERVICE_ACCOUNT'; set GCP_PROJECT."

GCP_AUTH_DIR=$PLUGIN_DIR
gcp_auth_mint() { GCP_SERVICE_ACCOUNT="$GCP_SERVICE_ACCOUNT" "$GCP_AUTH_DIR/host/mint-gcp-token.py"; }
# Tokens live 1h; 40 min leaves room for failed attempts, and every token the container's metadata
# server hands out has at least 20 min left.
register_credential gcp-token 2400 gcp_auth_mint

pass_value GCP_SERVICE_ACCOUNT "$GCP_SERVICE_ACCOUNT"
pass_value GCP_PROJECT "$GCP_AUTH_PROJECT"
echo "☁️  gcp-auth: $GCP_SERVICE_ACCOUNT (project $GCP_AUTH_PROJECT)"
