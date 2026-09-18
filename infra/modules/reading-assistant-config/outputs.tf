output "secret_parameter_names" {
  description = "Map of backend environment variable name to SSM parameter name. Referencing the resource attribute (not a computed string) makes consumers wait until the parameters exist."
  value       = { for key, parameter in aws_ssm_parameter.secret : key => parameter.name }
}

output "secret_parameter_arns" {
  description = "Map of backend environment variable name to SSM parameter ARN."
  value       = { for key, parameter in aws_ssm_parameter.secret : key => parameter.arn }
}
