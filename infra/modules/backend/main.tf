locals {
  project_name = "vicente-calderon"
  name_prefix  = "${local.project_name}-${var.environment}-backend"

  tags = {
    Project     = local.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_dynamodb_table" "personalized_examples" {
  name         = "${local.name_prefix}-personalized-examples"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  tags = local.tags
}

resource "aws_sqs_queue" "personalization_jobs_dlq" {
  name = "${local.name_prefix}-personalization-jobs-dlq"

  tags = local.tags
}

resource "aws_sqs_queue" "personalization_jobs" {
  name                       = "${local.name_prefix}-personalization-jobs"
  visibility_timeout_seconds = 180
  message_retention_seconds  = 345600

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.personalization_jobs_dlq.arn
    maxReceiveCount     = 5
  })

  tags = local.tags
}

resource "aws_iam_role" "personalization_worker" {
  name = "${local.name_prefix}-personalization-worker"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = local.tags
}

resource "aws_iam_role_policy_attachment" "personalization_worker_basic" {
  role       = aws_iam_role.personalization_worker.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "personalization_worker" {
  name = "${local.name_prefix}-personalization-worker"
  role = aws_iam_role.personalization_worker.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:ChangeMessageVisibility"
        ]
        Resource = aws_sqs_queue.personalization_jobs.arn
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:Query"
        ]
        Resource = aws_dynamodb_table.personalized_examples.arn
      }
    ]
  })
}

resource "aws_lambda_function" "personalization_worker" {
  count = var.worker_image_uri == null ? 0 : 1

  function_name = "${local.name_prefix}-personalization-worker"
  role          = aws_iam_role.personalization_worker.arn
  package_type  = "Image"
  image_uri     = var.worker_image_uri
  timeout       = 180

  image_config {
    command = ["personalization_worker"]
  }

  environment {
    variables = {
      PERSONALIZED_EXAMPLE_REPOSITORY          = "dynamodb"
      PERSONALIZED_EXAMPLE_DYNAMODB_TABLE_NAME = aws_dynamodb_table.personalized_examples.name
      PERSONALIZATION_JOB_PUBLISHER            = "sqs"
      PERSONALIZATION_JOBS_QUEUE_URL           = aws_sqs_queue.personalization_jobs.url
    }
  }

  tags = local.tags
}

resource "aws_lambda_event_source_mapping" "personalization_jobs" {
  count = var.worker_image_uri == null ? 0 : 1

  event_source_arn        = aws_sqs_queue.personalization_jobs.arn
  function_name           = aws_lambda_function.personalization_worker[0].arn
  batch_size              = 5
  function_response_types = ["ReportBatchItemFailures"]
}

