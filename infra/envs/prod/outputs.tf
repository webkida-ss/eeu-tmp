output "frontend_name_prefix" {
  description = "Common name prefix for prod frontend resources."
  value       = module.frontend.name_prefix
}

output "backend_name_prefix" {
  description = "Common name prefix for prod backend resources."
  value       = module.backend.name_prefix
}

output "cognito_user_pool_id" {
  description = "Prod Cognito User Pool ID."
  value       = module.auth.user_pool_id
}

output "cognito_app_client_id" {
  description = "Prod Cognito app client ID."
  value       = module.auth.app_client_id
}

output "cognito_authority" {
  description = "Prod Cognito OIDC authority URL."
  value       = module.auth.authority
}

output "cognito_hosted_ui_base_url" {
  description = "Prod Cognito Hosted UI base URL."
  value       = module.auth.hosted_ui_base_url
}

