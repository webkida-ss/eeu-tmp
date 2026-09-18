output "name_prefix" {
  description = "Common name prefix for backend resources."
  value       = local.name_prefix
}

output "personalization_jobs_queue_url" {
  description = "SQS queue URL for personalization regeneration jobs."
  value       = aws_sqs_queue.personalization_jobs.url
}

output "personalization_jobs_dlq_url" {
  description = "SQS dead-letter queue URL for personalization regeneration jobs."
  value       = aws_sqs_queue.personalization_jobs_dlq.url
}

output "personalized_examples_table_name" {
  description = "DynamoDB table name for stored personalized example sentences."
  value       = aws_dynamodb_table.personalized_examples.name
}

