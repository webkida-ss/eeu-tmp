output "user_pool_id" {
  description = "Cognito User Pool ID."
  value       = aws_cognito_user_pool.main.id
}

output "user_pool_arn" {
  description = "Cognito User Pool ARN."
  value       = aws_cognito_user_pool.main.arn
}

output "app_client_id" {
  description = "Cognito app client ID for the frontend."
  value       = aws_cognito_user_pool_client.web.id
}

output "authority" {
  description = "OIDC authority URL for the User Pool."
  value       = "https://cognito-idp.${data.aws_region.current.name}.amazonaws.com/${aws_cognito_user_pool.main.id}"
}

output "hosted_ui_base_url" {
  description = "Cognito Hosted UI base URL."
  value       = "https://${aws_cognito_user_pool_domain.main.domain}.auth.${data.aws_region.current.name}.amazoncognito.com"
}

output "domain_prefix" {
  description = "Cognito Hosted UI domain prefix."
  value       = aws_cognito_user_pool_domain.main.domain
}
