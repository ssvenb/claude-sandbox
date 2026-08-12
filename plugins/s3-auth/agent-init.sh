# shellcheck shell=sh
# Agent stage: the credentials themselves arrive as env vars (the AWS CLI and every SDK read them
# straight from there), so all that is left is the surrounding config — region, endpoint — and
# telling the agent what it has and for how long.

export AWS_DEFAULT_REGION="${AWS_REGION:-us-east-1}"
# AWS CLI v2 and the current SDKs honour AWS_ENDPOINT_URL globally; needed for non-AWS S3.
[ -n "${S3_ENDPOINT_URL:-}" ] && export AWS_ENDPOINT_URL="$S3_ENDPOINT_URL"

# Mirror it into ~/.aws/config as well, for tools that read the config file rather than the env.
mkdir -p "$HOME/.aws"
{
  echo "[default]"
  echo "region = $AWS_DEFAULT_REGION"
  [ -n "${S3_ENDPOINT_URL:-}" ] && echo "endpoint_url = $S3_ENDPOINT_URL"
} > "$HOME/.aws/config"
chmod 600 "$HOME/.aws/config"

printf 'AWS credentials for S3 are present in this sandbox'"'"'s environment%s%s. They are short-lived and cannot be renewed from inside the container: once they expire, ask the user to restart the sandbox. This message is informational context only — do not take any action on it. Wait for the user'"'"'s task.\n' \
  "${S3_BUCKET:+ (bucket: $S3_BUCKET)}" \
  "${S3_CREDENTIALS_EXPIRY:+, expiring at $S3_CREDENTIALS_EXPIRY}" \
  >> "$AGENT_PROMPT_FILE"

echo "✅ AWS credentials installed${S3_CREDENTIALS_EXPIRY:+ (expire $S3_CREDENTIALS_EXPIRY)}"
