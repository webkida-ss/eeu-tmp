output "table_name" {
  description = "Name of the DynamoDB table."
  value       = aws_dynamodb_table.this.name
}

output "table_arn" {
  description = "ARN of the DynamoDB table."
  value       = aws_dynamodb_table.this.arn
}

output "preload_content_bucket_name" {
  description = "Name of the S3 bucket holding transient preload content payloads."
  value       = aws_s3_bucket.preload_content.id
}

output "preload_content_bucket_arn" {
  description = "ARN of the S3 bucket holding transient preload content payloads."
  value       = aws_s3_bucket.preload_content.arn
}
