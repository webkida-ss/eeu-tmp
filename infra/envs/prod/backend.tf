# Remote state in a shared S3 bucket, with a stack-scoped key so this
# stack's lifecycle is independent from other stacks in the same bucket.
# S3-native lock files are used instead of a DynamoDB lock table.
#
# The bucket name is account-specific and is supplied at init time:
#   terraform init -backend-config=backend.hcl
# Copy backend.hcl.example to backend.hcl (gitignored) for local use.
# CI passes -backend-config=bucket=$TERRAFORM_STATE_BUCKET.
terraform {
  backend "s3" {
    key          = "02_english/reading-assistant/prod/terraform.tfstate"
    region       = "ap-northeast-1"
    encrypt      = true
    use_lockfile = true
  }
}
