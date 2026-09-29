# SSM parameters are managed manually, not in Terraform.
# This prevents accidental resets when Terraform recreates resources.
#
# Setup commands (run once):
#
# aws ssm put-parameter \
#   --name "/brag/openrouter_api_key" \
#   --value "sk-or-v1-YOUR_KEY" \
#   --type SecureString \
#   --region eu-north-1
#
# aws ssm put-parameter \
#   --name "/brag/mongodb_uri" \
#   --value "mongodb+srv://user:pass@cluster.mongodb.net/" \
#   --type SecureString \
#   --region eu-north-1
#
# aws ssm put-parameter \
#   --name "/brag/auth_secret" \
#   --value "YOUR_JWT_SECRET" \
#   --type SecureString \
#   --region eu-north-1
#
# aws ssm put-parameter \
#   --name "/brag/cors_origins" \
#   --value "https://brag.bobbyugbebor.store" \
#   --type String \
#   --region eu-north-1
