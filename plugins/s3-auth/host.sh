# shellcheck shell=bash
# Host stage. The whole point of this plugin: the durable AWS credential (your IAM user's access
# key, your SSO session) never enters the container. It is used HERE, on the host, to mint a
# short-lived session, and only that session's keys are passed in. They expire on their own —
# there is deliberately no in-container refresh loop, because refreshing would require shipping
# the durable credential the agent must not have.
#
# Two modes:
#   S3_ROLE_ARN set  → sts assume-role, so the agent's reach is exactly that role's policy.
#   S3_ROLE_ARN unset → export whatever credentials the host's profile currently resolves to.
# The first is strongly preferred: it is the only one that also narrows *what* the agent can do.

command -v aws >/dev/null || die "s3-auth needs the AWS CLI on the host to mint session credentials."

_aws_profile_args=()
[ -n "${AWS_PROFILE:-}" ] && _aws_profile_args=(--profile "$AWS_PROFILE")

if [ -n "${S3_ROLE_ARN:-}" ]; then
  # Session name ties the CloudTrail entries back to this sandbox. RUN_ID is not minted yet at
  # host-stage time, so use a timestamp.
  _s3_creds=$(aws "${_aws_profile_args[@]}" sts assume-role \
                --role-arn "$S3_ROLE_ARN" \
                --role-session-name "claude-sandbox-$(date +%s)" \
                --duration-seconds "${S3_SESSION_DURATION:-3600}" \
                --query Credentials --output json) \
    || die "s3-auth: assume-role on $S3_ROLE_ARN failed — is your host AWS login active and trusted by that role?"
else
  _s3_creds=$(aws "${_aws_profile_args[@]}" configure export-credentials --format process) \
    || die "s3-auth: no AWS credentials on the host (configure a profile, or set S3_ROLE_ARN)."
fi

_s3_key=$(jq -r '.AccessKeyId // empty' <<<"$_s3_creds")
_s3_secret=$(jq -r '.SecretAccessKey // empty' <<<"$_s3_creds")
_s3_token=$(jq -r '.SessionToken // empty' <<<"$_s3_creds")
_s3_expiry=$(jq -r '.Expiration // empty' <<<"$_s3_creds")
[ -n "$_s3_key" ] && [ -n "$_s3_secret" ] || die "s3-auth: could not read credentials from the AWS CLI output."

if [ -z "$_s3_token" ]; then
  # No session token means these are long-lived user keys, valid until you rotate them by hand.
  echo "⚠️  s3-auth is passing LONG-LIVED AWS keys into the container (no session token). Set S3_ROLE_ARN to hand the agent a short-lived, narrowly-scoped session instead."
fi

pass_value AWS_ACCESS_KEY_ID "$_s3_key"
pass_value AWS_SECRET_ACCESS_KEY "$_s3_secret"
[ -n "$_s3_token" ] && pass_value AWS_SESSION_TOKEN "$_s3_token"
[ -n "$_s3_expiry" ] && pass_value S3_CREDENTIALS_EXPIRY "$_s3_expiry"

# Region and, for S3-compatible providers (MinIO, IONOS, Cloudflare R2, …), the endpoint.
pass_value AWS_REGION "${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
pass_env S3_ENDPOINT_URL S3_BUCKET

unset _s3_creds _s3_key _s3_secret _s3_token _s3_expiry _aws_profile_args
