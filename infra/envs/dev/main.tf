locals {
  environment = "dev"
}

module "frontend" {
  source = "../../modules/frontend"

  environment = local.environment
}

module "backend" {
  source = "../../modules/backend"

  environment = local.environment
}

module "auth" {
  source = "../../modules/auth"

  environment           = local.environment
  google_client_id      = var.google_client_id
  google_client_secret  = var.google_client_secret
  callback_urls         = var.auth_callback_urls
  logout_urls           = var.auth_logout_urls
  cognito_domain_prefix = var.cognito_domain_prefix
}

