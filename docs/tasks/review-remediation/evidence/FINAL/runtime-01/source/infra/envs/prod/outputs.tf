output "api_endpoint" {
  description = "Base URL of the backend API. Point the extension (and API_BASE_URL) here."
  value       = module.api.api_endpoint
}

output "dynamodb_table_name" {
  description = "Name of the DynamoDB table."
  value       = module.data.table_name
}

output "preload_content_bucket_name" {
  description = "Name of the S3 bucket holding transient preload content payloads."
  value       = module.data.preload_content_bucket_name
}

output "lambda_function_name" {
  description = "Name of the backend Lambda function."
  value       = module.api.lambda_function_name
}

output "secret_parameter_names" {
  description = "SSM parameter names to populate with real secret values."
  value       = module.config.secret_parameter_names
}

output "alerts_topic_arn" {
  description = "SNS topic for budget/abuse notifications."
  value       = module.alerting.alerts_topic_arn
}
