# SecureString SSM parameters (standard tier, which is free) that hold the
# backend secrets. Terraform only creates the parameters with a placeholder
# value; the real values are set out-of-band and never enter Terraform state
# as configuration:
#
#   aws ssm put-parameter \
#     --name "/<project>/<env>/reading-assistant/OPENAI_API_KEY" \
#     --type SecureString --value "sk-..." --overwrite
#
# `ignore_changes = [value]` keeps subsequent plans from reverting the real
# value back to the placeholder.
locals {
  secret_names = toset([
    "OPENAI_API_KEY",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
  ])
}

resource "aws_ssm_parameter" "secret" {
  for_each = local.secret_names

  name        = "/${var.project}/${var.environment}/reading-assistant/${each.key}"
  description = "Reading-assistant backend secret ${each.key} (${var.environment}). Set the real value with `aws ssm put-parameter --overwrite`."
  type        = "SecureString"
  tier        = "Standard"
  value       = "REPLACE_ME"

  lifecycle {
    ignore_changes = [value]
  }
}
