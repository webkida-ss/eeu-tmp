locals {
  name_prefix          = "${var.project}-${var.environment}-reading-assistant"
  function_name        = "${local.name_prefix}-api"
  worker_function_name = "${local.name_prefix}-worker"

  # Non-secret application configuration. The FastAPI app reads plain
  # environment variables (see backend/config.py).
  base_environment = {
    STORAGE_BACKEND                       = "dynamodb"
    READING_ASSISTANT_DYNAMODB_TABLE_NAME = var.table_name
    AUTH_PROVIDER                         = var.auth_provider
    GOOGLE_OAUTH_CLIENT_ID                = var.google_oauth_client_id
    BILLING_PROVIDER                      = var.billing_provider
    STRIPE_PRICE_ID_PRO                   = var.stripe_price_id_pro
    STRIPE_PRICE_ID_MAX                   = var.stripe_price_id_max
    # Article analysis is deferred to the worker Lambda over SQS so it is not
    # bound by API Gateway's 30-second integration cap. The API only enqueues.
    JOB_RUNNER             = "sqs"
    PRELOAD_JOBS_QUEUE_URL = aws_sqs_queue.preload_jobs.id
    # The raw extracted article text is stored transiently in S3 (submit ->
    # worker handoff), not in the DynamoDB record. Setting this selects the
    # S3 content store (see config.py PRELOAD_CONTENT_BUCKET).
    PRELOAD_CONTENT_BUCKET = var.preload_content_bucket_name
    # An empty value is deliberate: the app then allows only the
    # chrome-extension:// origin regex it enforces itself.
    ALLOWED_ORIGINS = join(",", var.allowed_origins)
  }

  usage_environment = merge(var.usage_pricing_and_plan_environment, {
    USAGE_RESERVATION_ENABLED        = tostring(var.usage_reservation_enabled)
    USAGE_RESERVATION_TTL_SECONDS    = tostring(var.usage_reservation_ttl_seconds)
    SYNC_RESULT_TTL_SECONDS          = tostring(var.sync_result_ttl_seconds)
    SYNC_RESULT_MAX_BYTES            = tostring(var.sync_result_max_bytes)
    SYNC_RESULT_CLEANUP_BATCH_SIZE   = tostring(var.sync_result_cleanup_batch_size)
    SYNC_EXECUTION_LEASE_SECONDS     = tostring(var.sync_execution_lease_seconds)
    SYNC_EXECUTION_WAIT_SECONDS      = tostring(var.sync_execution_wait_seconds)
    PRELOAD_WORKER_LEASE_SECONDS     = tostring(var.preload_worker_lease_seconds)
    OPENAI_MAX_INPUT_TOKENS_PER_CALL = tostring(var.openai_max_input_tokens_per_call)
    MAX_SENTENCE_SPLIT_AGENT_TURNS   = tostring(var.max_sentence_split_agent_turns)
  })

  # Pass SSM parameter names only. The process reads values at runtime so
  # secret material never enters Terraform state or Lambda configuration.
  secret_environment = {
    for key, name in var.secret_parameter_names : "${key}_SSM_PARAMETER" => name
  }

  lambda_environment = merge(
    local.base_environment,
    var.extra_environment,
    local.usage_environment,
    local.secret_environment,
  )

  provider_environment_is_preserved = (
    local.lambda_environment["STORAGE_BACKEND"] == "dynamodb" &&
    local.lambda_environment["READING_ASSISTANT_DYNAMODB_TABLE_NAME"] == var.table_name &&
    local.lambda_environment["AUTH_PROVIDER"] == var.auth_provider &&
    local.lambda_environment["GOOGLE_OAUTH_CLIENT_ID"] == var.google_oauth_client_id &&
    local.lambda_environment["BILLING_PROVIDER"] == var.billing_provider &&
    local.lambda_environment["STRIPE_PRICE_ID_PRO"] == var.stripe_price_id_pro &&
    local.lambda_environment["STRIPE_PRICE_ID_MAX"] == var.stripe_price_id_max &&
    local.lambda_environment["JOB_RUNNER"] == "sqs" &&
    local.lambda_environment["PRELOAD_JOBS_QUEUE_URL"] == aws_sqs_queue.preload_jobs.id &&
    local.lambda_environment["PRELOAD_CONTENT_BUCKET"] == var.preload_content_bucket_name &&
    local.lambda_environment["ALLOWED_ORIGINS"] == join(",", var.allowed_origins)
  )

  production_provider_environment_is_safe = var.environment != "prod" || (
    local.lambda_environment["STORAGE_BACKEND"] == "dynamodb" &&
    local.lambda_environment["AUTH_PROVIDER"] == "google" &&
    local.lambda_environment["BILLING_PROVIDER"] == "stripe"
  )
}

check "usage_pricing_required_when_enforced" {
  assert {
    condition = !var.usage_reservation_enabled || (
      trimspace(lookup(var.usage_pricing_and_plan_environment, "OPENAI_RATE_CARD_VERSION", "")) != "" &&
      try(tonumber(lookup(var.usage_pricing_and_plan_environment, "OPENAI_MODEL_INPUT_MICRO_USD_PER_MILLION", "")), 0) > 0 &&
      try(tonumber(lookup(var.usage_pricing_and_plan_environment, "OPENAI_MODEL_OUTPUT_MICRO_USD_PER_MILLION", "")), 0) > 0
    )
    error_message = "USAGE_RESERVATION_ENABLED requires a rate-card version and positive input/output model rates."
  }
}

# --- IAM (least privilege: the one table plus its own log group) ---------

data "aws_iam_policy_document" "assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${local.function_name}-role"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
}

data "aws_iam_policy_document" "lambda" {
  statement {
    sid = "DynamoDbSingleTableAccess"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:Query",
      "dynamodb:BatchGetItem",
      "dynamodb:BatchWriteItem",
      "dynamodb:ConditionCheckItem",
      "dynamodb:TransactWriteItems",
      "dynamodb:DescribeTable",
    ]
    resources = [
      var.table_arn,
      "${var.table_arn}/index/*",
    ]
  }

  statement {
    sid = "WriteOwnLogGroup"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.lambda.arn}:*"]
  }

  statement {
    sid       = "EnqueuePreloadJobs"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.preload_jobs.arn]
  }

  # The API only writes the handoff payload; the worker reads and deletes it.
  statement {
    sid       = "PutPreloadContent"
    actions   = ["s3:PutObject"]
    resources = ["${var.preload_content_bucket_arn}/preload-content/*"]
  }

  statement {
    sid       = "ReadSecretParameters"
    actions   = ["ssm:GetParameter"]
    resources = values(var.secret_parameter_arns)
  }
}

resource "aws_iam_role_policy" "lambda" {
  name   = "${local.function_name}-policy"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda.json
}

# --- Logs -----------------------------------------------------------------

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = var.log_retention_in_days
}

# --- Lambda ---------------------------------------------------------------

# The zip artifact is built outside Terraform by
# backend/scripts/build_lambda.sh.
resource "aws_lambda_function" "this" {
  function_name = local.function_name
  role          = aws_iam_role.lambda.arn

  filename         = var.lambda_zip_path
  source_code_hash = filebase64sha256(var.lambda_zip_path)

  runtime       = "python3.12"
  architectures = ["arm64"]
  handler       = "lambda_handler.handler"

  memory_size = var.lambda_memory_size
  timeout     = var.lambda_timeout

  # Caps parallel executions as a blast-radius limit against runaway or
  # abusive traffic. -1 leaves the account default (uncapped).
  reserved_concurrent_executions = var.reserved_concurrent_executions

  environment {
    variables = local.lambda_environment
  }

  lifecycle {
    precondition {
      condition = !var.usage_reservation_enabled || (
        trimspace(lookup(var.usage_pricing_and_plan_environment, "OPENAI_RATE_CARD_VERSION", "")) != "" &&
        try(tonumber(lookup(var.usage_pricing_and_plan_environment, "OPENAI_MODEL_INPUT_MICRO_USD_PER_MILLION", "")), 0) > 0 &&
        try(tonumber(lookup(var.usage_pricing_and_plan_environment, "OPENAI_MODEL_OUTPUT_MICRO_USD_PER_MILLION", "")), 0) > 0
      )
      error_message = "Usage reservation enforcement requires configured positive OpenAI rates and a rate-card version."
    }

    precondition {
      condition = (
        local.provider_environment_is_preserved &&
        local.production_provider_environment_is_safe
      )
      error_message = "Final API Lambda environment must preserve typed provider and storage settings and use dynamodb, google, and stripe in prod."
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda]
}

# --- API Gateway HTTP API (v2) ---------------------------------------------

# No cors_configuration on purpose: the FastAPI app already handles CORS
# (ALLOWED_ORIGINS plus a chrome-extension:// origin regex), and API Gateway
# CORS would shadow it. Pass-through is correct here.
resource "aws_apigatewayv2_api" "this" {
  name          = "${local.name_prefix}-http-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.this.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true

  # First line of defense against token-burn abuse: stage-wide throttling.
  default_route_settings {
    throttling_burst_limit = var.throttling_burst_limit
    throttling_rate_limit  = var.throttling_rate_limit
  }
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.this.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}

# --- Async preload pipeline (SQS + worker Lambda) --------------------------

# Dead-letter queue: a job that keeps failing to be processed after
# maxReceiveCount attempts lands here instead of retrying forever.
resource "aws_sqs_queue" "preload_jobs_dlq" {
  name                      = "${local.name_prefix}-preload-jobs-dlq"
  message_retention_seconds = 1209600 # 14 days (the SQS maximum) for triage.
}

resource "aws_sqs_queue" "preload_jobs" {
  name = "${local.name_prefix}-preload-jobs"

  # Visibility timeout must exceed the worker timeout so a message is not
  # redelivered while still being processed; AWS recommends >= 6x the
  # function timeout to absorb retries and batching.
  visibility_timeout_seconds = var.worker_lambda_timeout * 6

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.preload_jobs_dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/aws/lambda/${local.worker_function_name}"
  retention_in_days = var.log_retention_in_days
}

# The worker runs the same code artifact as the API Lambda, entered through
# worker_handler.handler (an SQS batch handler) instead of the ASGI adapter.
data "aws_iam_policy_document" "worker" {
  statement {
    sid = "DynamoDbSingleTableAccess"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:Query",
      "dynamodb:BatchGetItem",
      "dynamodb:BatchWriteItem",
      "dynamodb:ConditionCheckItem",
      "dynamodb:TransactWriteItems",
      "dynamodb:DescribeTable",
    ]
    resources = [
      var.table_arn,
      "${var.table_arn}/index/*",
    ]
  }

  statement {
    sid = "WriteOwnLogGroup"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.worker.arn}:*"]
  }

  statement {
    sid = "ConsumePreloadJobs"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
    ]
    resources = [aws_sqs_queue.preload_jobs.arn]
  }

  # The worker reads the handoff payload written by the API and deletes it
  # once the analysis has consumed it.
  statement {
    sid = "ReadDeletePreloadContent"
    actions = [
      "s3:GetObject",
      "s3:DeleteObject",
    ]
    resources = ["${var.preload_content_bucket_arn}/preload-content/*"]
  }

  statement {
    sid       = "ReadSecretParameters"
    actions   = ["ssm:GetParameter"]
    resources = values(var.secret_parameter_arns)
  }
}

resource "aws_iam_role" "worker" {
  name               = "${local.worker_function_name}-role"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
}

resource "aws_iam_role_policy" "worker" {
  name   = "${local.worker_function_name}-policy"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.worker.json
}

resource "aws_lambda_function" "worker" {
  function_name = local.worker_function_name
  role          = aws_iam_role.worker.arn

  filename         = var.lambda_zip_path
  source_code_hash = filebase64sha256(var.lambda_zip_path)

  runtime       = "python3.12"
  architectures = ["arm64"]
  handler       = "worker_handler.handler"

  memory_size = var.worker_lambda_memory_size
  timeout     = var.worker_lambda_timeout

  environment {
    variables = local.lambda_environment
  }

  lifecycle {
    precondition {
      condition = (
        local.provider_environment_is_preserved &&
        local.production_provider_environment_is_safe
      )
      error_message = "Final worker Lambda environment must preserve typed provider and storage settings and use dynamodb, google, and stripe in prod."
    }
  }

  depends_on = [aws_cloudwatch_log_group.worker]
}

# One message per invocation (batch_size 1): each preload job is a long,
# independent unit of work, and partial-batch reporting keeps a poison
# message from re-running the others.
resource "aws_lambda_event_source_mapping" "worker" {
  event_source_arn                   = aws_sqs_queue.preload_jobs.arn
  function_name                      = aws_lambda_function.worker.arn
  batch_size                         = 1
  function_response_types            = ["ReportBatchItemFailures"]
  maximum_batching_window_in_seconds = 0
}
