# shellcheck shell=sh
# Agent stage: the credentials arrive as env vars, which the AWS CLI and every SDK read directly,
# so only the surrounding config is left — plus telling the agent what it has and for how long.

export AWS_DEFAULT_REGION="${AWS_REGION:-us-east-1}"
# AWS CLI v2 and the current SDKs honour AWS_ENDPOINT_URL globally; needed for non-AWS S3.
[ -n "${S3_ENDPOINT_URL:-}" ] && export AWS_ENDPOINT_URL="$S3_ENDPOINT_URL"

# Mirrored into ~/.aws/config too, for tools that read the config file rather than the env.
mkdir -p "$HOME/.aws"
{
  echo "[default]"
  echo "region = $AWS_DEFAULT_REGION"
  [ -n "${S3_ENDPOINT_URL:-}" ] && echo "endpoint_url = $S3_ENDPOINT_URL"
} > "$HOME/.aws/config"
chmod 600 "$HOME/.aws/config"

printf 'AWS credentials for S3 are present in this sandbox'"'"'s environment%s%s. They are short-lived and cannot be renewed from inside the container: once they expire, ask the user to restart the sandbox.\n' \
  "${S3_BUCKET:+ (bucket: $S3_BUCKET)}" \
  "${S3_CREDENTIALS_EXPIRY:+, expiring at $S3_CREDENTIALS_EXPIRY}" \
  >> "$AGENT_PROMPT_FILE"

echo "✅ AWS credentials installed${S3_CREDENTIALS_EXPIRY:+ (expire $S3_CREDENTIALS_EXPIRY)}"
