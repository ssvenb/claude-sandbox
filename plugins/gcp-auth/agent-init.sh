# shellcheck shell=sh
# Agent stage. Tell the agent it already has a Google Cloud identity, so it uses it as is instead of
# hunting for a key file or trying to log in.

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
