output "frontend_name_prefix" {
  description = "Common name prefix for dev frontend resources."
  value       = module.frontend.name_prefix
}

output "backend_name_prefix" {
  description = "Common name prefix for dev backend resources."
  value       = module.backend.name_prefix
}

output "cognito_user_pool_id" {
  description = "Dev Cognito User Pool ID."
  value       = module.auth.user_pool_id
}

output "cognito_app_client_id" {
  description = "Dev Cognito app client ID."
  value       = module.auth.app_client_id
}

output "cognito_authority" {
  description = "Dev Cognito OIDC authority URL."
  value       = module.auth.authority
}

output "cognito_hosted_ui_base_url" {
  description = "Dev Cognito Hosted UI base URL."
  value       = module.auth.hosted_ui_base_url
}

