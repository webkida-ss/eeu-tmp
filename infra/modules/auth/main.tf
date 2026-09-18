data "aws_region" "current" {}

locals {
  project_name  = "vicente-calderon"
  name_prefix   = "${local.project_name}-${var.environment}-auth"
  domain_prefix = coalesce(var.cognito_domain_prefix, local.name_prefix)

  tags = {
    Project     = local.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_cognito_user_pool" "main" {
  name = "${local.name_prefix}-user-pool"

  auto_verified_attributes = ["email"]
  username_attributes      = ["email"]

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  tags = local.tags
}

resource "aws_cognito_identity_provider" "google" {
  user_pool_id  = aws_cognito_user_pool.main.id
  provider_name = "Google"
  provider_type = "Google"

  provider_details = {
    authorize_scopes = "openid email profile"
    client_id        = var.google_client_id
    client_secret    = var.google_client_secret
  }

  attribute_mapping = {
    email    = "email"
    username = "sub"
  }
}

resource "aws_cognito_user_pool_client" "web" {
  name         = "${local.name_prefix}-web"
  user_pool_id = aws_cognito_user_pool.main.id

  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  callback_urls                        = var.callback_urls
  logout_urls                          = var.logout_urls
  supported_identity_providers         = [aws_cognito_identity_provider.google.provider_name]
  prevent_user_existence_errors        = "ENABLED"
}

resource "aws_cognito_user_pool_domain" "main" {
  domain       = local.domain_prefix
  user_pool_id = aws_cognito_user_pool.main.id
}
