output "api_endpoint" {
  description = "Invoke URL of the HTTP API ($default stage)."
  value       = aws_apigatewayv2_api.this.api_endpoint
}

output "api_id" {
  description = "ID of the HTTP API."
  value       = aws_apigatewayv2_api.this.id
}

output "lambda_function_name" {
  description = "Name of the backend Lambda function."
  value       = aws_lambda_function.this.function_name
}

output "lambda_function_arn" {
  description = "ARN of the backend Lambda function."
  value       = aws_lambda_function.this.arn
}

output "lambda_role_name" {
  description = "Name of the Lambda execution role."
  value       = aws_iam_role.lambda.name
}

output "log_group_name" {
  description = "Name of the Lambda CloudWatch log group."
  value       = aws_cloudwatch_log_group.lambda.name
}

output "worker_function_name" {
  description = "Name of the async preload worker Lambda function."
  value       = aws_lambda_function.worker.function_name
}

output "worker_log_group_name" {
  description = "Name of the worker Lambda CloudWatch log group."
  value       = aws_cloudwatch_log_group.worker.name
}

output "preload_jobs_queue_url" {
  description = "URL of the preload jobs SQS queue."
  value       = aws_sqs_queue.preload_jobs.id
}

output "preload_jobs_dlq_url" {
  description = "URL of the preload jobs dead-letter queue."
  value       = aws_sqs_queue.preload_jobs_dlq.id
}
