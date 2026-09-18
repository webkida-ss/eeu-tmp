variable "project" {
  description = "Project prefix used in resource names (e.g. \"english\")."
  type        = string
}

variable "environment" {
  description = "Environment name used in resource names (e.g. \"dev\", \"prod\")."
  type        = string
}

variable "lambda_zip_path" {
  description = "Path to the pre-built Lambda zip artifact (built by backend/scripts/build_lambda.sh)."
  type        = string

  validation {
    condition     = fileexists(var.lambda_zip_path)
    error_message = "lambda_zip_path does not exist. Run backend/scripts/build_lambda.sh first."
  }
}

variable "table_name" {
  description = "Name of the DynamoDB table the backend uses."
  type        = string
}

variable "table_arn" {
  description = "ARN of the DynamoDB table the backend uses."
  type        = string
}

variable "preload_content_bucket_name" {
  description = "Name of the S3 bucket holding transient preload content payloads (the submit -> worker handoff of the raw extracted article text)."
  type        = string
}

variable "preload_content_bucket_arn" {
  description = "ARN of the S3 bucket holding transient preload content payloads."
  type        = string
}

variable "secret_parameter_names" {
  description = "Map of backend environment variable name to the SSM SecureString parameter name (from the reading-assistant-config module). Values stay out of Terraform."
  type        = map(string)
}

variable "secret_parameter_arns" {
  description = "Map of backend environment variable name to the SSM SecureString parameter ARN used for runtime GetParameter."
  type        = map(string)

  validation {
    condition = (
      length(var.secret_parameter_arns) > 0 &&
      toset(keys(var.secret_parameter_names)) == toset(keys(var.secret_parameter_arns))
    )
    error_message = "secret_parameter_arns must be a non-empty map with the same keys as secret_parameter_names."
  }
}

variable "auth_provider" {
  description = "Identity provider for sign-in: \"google\" or \"mock\"."
  type        = string
  default     = "google"

  validation {
    condition     = contains(["google", "mock"], var.auth_provider)
    error_message = "auth_provider must be \"google\" or \"mock\"."
  }

  # Production guardrail: the mock provider accepts any caller, which would
  # be both an auth bypass and unlimited OpenAI token burn.
  validation {
    condition     = var.environment != "prod" || var.auth_provider == "google"
    error_message = "In prod, auth_provider must be \"google\". The mock identity provider must never run in production."
  }
}

variable "google_oauth_client_id" {
  description = "Google OAuth client ID used to verify Google ID tokens (required when auth_provider is \"google\")."
  type        = string
  default     = ""
  sensitive   = true

  validation {
    condition     = var.auth_provider != "google" || length(var.google_oauth_client_id) > 0
    error_message = "google_oauth_client_id is required when auth_provider is \"google\"."
  }
}

variable "billing_provider" {
  description = "Billing provider: \"stripe\" or \"mock\"."
  type        = string
  default     = "stripe"

  validation {
    condition     = contains(["stripe", "mock"], var.billing_provider)
    error_message = "billing_provider must be \"stripe\" or \"mock\"."
  }

  # Production guardrail: mock billing grants paid plans (and their large
  # token quotas) without payment.
  validation {
    condition     = var.environment != "prod" || var.billing_provider == "stripe"
    error_message = "In prod, billing_provider must be \"stripe\". The mock billing provider must never run in production."
  }
}

variable "stripe_price_id_pro" {
  description = "Stripe price ID for the pro plan (required when billing_provider is \"stripe\")."
  type        = string
  default     = ""
  sensitive   = true

  validation {
    condition     = var.billing_provider != "stripe" || length(var.stripe_price_id_pro) > 0
    error_message = "stripe_price_id_pro is required when billing_provider is \"stripe\"."
  }
}

variable "stripe_price_id_max" {
  description = "Stripe price ID for the max plan (required when billing_provider is \"stripe\")."
  type        = string
  default     = ""
  sensitive   = true

  validation {
    condition     = var.billing_provider != "stripe" || length(var.stripe_price_id_max) > 0
    error_message = "stripe_price_id_max is required when billing_provider is \"stripe\"."
  }
}

variable "allowed_origins" {
  description = "Extra CORS origins passed to the app as ALLOWED_ORIGINS. chrome-extension:// origins are always allowed by the app itself, so this is usually empty."
  type        = list(string)
  default     = []
}

variable "extra_environment" {
  description = "Additional non-secret environment variables for the app. Provider, storage, identity, billing, usage, pricing, plan, lease, and replay-retention keys must use their typed inputs."
  type        = map(string)
  default     = {}
  sensitive   = true

  # RESERVED_USAGE_ENVIRONMENT_KEYS and provider/security keys are owned by typed inputs.
  validation {
    condition = length(setintersection(toset(keys(var.extra_environment)), toset([
      "STORAGE_BACKEND", "READING_ASSISTANT_DYNAMODB_TABLE_NAME",
      "AUTH_PROVIDER", "GOOGLE_OAUTH_CLIENT_ID", "AUTH_SESSION_TTL_DAYS",
      "BILLING_PROVIDER", "STRIPE_PRICE_ID_PRO", "STRIPE_PRICE_ID_MAX",
      "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
      "OPENAI_API_KEY", "OPENAI_API_KEY_SSM_PARAMETER",
      "STRIPE_SECRET_KEY_SSM_PARAMETER", "STRIPE_WEBHOOK_SECRET_SSM_PARAMETER",
      "JOB_RUNNER", "PRELOAD_JOBS_QUEUE_URL", "PRELOAD_CONTENT_BUCKET",
      "PRELOAD_CONTENT_DIR", "ALLOWED_ORIGINS",
      "USAGE_RESERVATION_ENABLED", "USAGE_RESERVATION_TTL_SECONDS",
      "SYNC_RESULT_TTL_SECONDS", "SYNC_RESULT_MAX_BYTES",
      "SYNC_RESULT_CLEANUP_BATCH_SIZE", "SYNC_EXECUTION_LEASE_SECONDS",
      "SYNC_EXECUTION_WAIT_SECONDS", "PRELOAD_WORKER_LEASE_SECONDS",
      "OPENAI_MAX_INPUT_TOKENS_PER_CALL", "MAX_SENTENCE_SPLIT_AGENT_TURNS",
      "OPENAI_TOKEN_ENCODING", "OPENAI_RATE_CARD_VERSION",
      "OPENAI_MODEL_INPUT_MICRO_USD_PER_MILLION",
      "OPENAI_MODEL_OUTPUT_MICRO_USD_PER_MILLION",
      "PLAN_BASIC_ARTICLES_PER_MONTH", "PLAN_BASIC_CHATS_PER_MONTH",
      "PLAN_BASIC_SENTENCES_PER_ARTICLE", "PLAN_BASIC_SOURCE_TOKENS_PER_ARTICLE",
      "PLAN_BASIC_COST_MICRO_USD_PER_MONTH", "PLAN_BASIC_TOKENS_PER_MONTH",
      "PLAN_PRO_ARTICLES_PER_MONTH", "PLAN_PRO_CHATS_PER_MONTH",
      "PLAN_PRO_SENTENCES_PER_ARTICLE", "PLAN_PRO_SOURCE_TOKENS_PER_ARTICLE",
      "PLAN_PRO_COST_MICRO_USD_PER_MONTH", "PLAN_PRO_TOKENS_PER_MONTH",
      "PLAN_MAX_ARTICLES_PER_MONTH", "PLAN_MAX_CHATS_PER_MONTH",
      "PLAN_MAX_SENTENCES_PER_ARTICLE", "PLAN_MAX_SOURCE_TOKENS_PER_ARTICLE",
      "PLAN_MAX_COST_MICRO_USD_PER_MONTH", "PLAN_MAX_TOKENS_PER_MONTH",
    ]))) == 0
    error_message = "extra_environment cannot override reserved provider, storage, identity, billing, security, usage, pricing, plan, lease, or replay-retention keys."
  }
}

variable "usage_reservation_enabled" {
  description = "Enable atomic composite usage reservations only after staging concurrency verification."
  type        = bool
  default     = false
}

variable "usage_reservation_ttl_seconds" {
  description = "Reservation lease duration in seconds."
  type        = number
  default     = 900
}

variable "sync_result_ttl_seconds" {
  description = "Retention for private synchronous replay records."
  type        = number
  default     = 86400
}

variable "sync_result_max_bytes" {
  description = "Maximum serialized synchronous replay result size."
  type        = number
  default     = 65536
}

variable "sync_result_cleanup_batch_size" {
  description = "Maximum expired JSON replay records cleaned per operation."
  type        = number
  default     = 100
}

variable "sync_execution_lease_seconds" {
  description = "Lease duration for a synchronous provider execution."
  type        = number
  default     = 120
}

variable "sync_execution_wait_seconds" {
  description = "Maximum wait for an in-flight synchronous execution."
  type        = number
  default     = 2
}

variable "preload_worker_lease_seconds" {
  description = "Lease duration for async preload worker ownership."
  type        = number
  default     = 900
}

variable "openai_max_input_tokens_per_call" {
  description = "Maximum input-plus-output token envelope accepted for one OpenAI call."
  type        = number
  default     = 128000

  validation {
    condition     = floor(var.openai_max_input_tokens_per_call) == var.openai_max_input_tokens_per_call && var.openai_max_input_tokens_per_call >= 1 && var.openai_max_input_tokens_per_call <= 1000000
    error_message = "openai_max_input_tokens_per_call must be an integer between 1 and 1000000."
  }
}

variable "max_sentence_split_agent_turns" {
  description = "Maximum fallback split-agent turns per article chunk."
  type        = number
  default     = 2

  validation {
    condition     = floor(var.max_sentence_split_agent_turns) == var.max_sentence_split_agent_turns && var.max_sentence_split_agent_turns >= 1 && var.max_sentence_split_agent_turns <= 8
    error_message = "max_sentence_split_agent_turns must be an integer between 1 and 8."
  }
}

variable "usage_pricing_and_plan_environment" {
  description = "Non-secret tokenizer, pinned rate-card, and PLAN_* settings. Empty rates intentionally fail closed when enforcement is enabled."
  type        = map(string)
  default = {
    OPENAI_TOKEN_ENCODING                     = "o200k_base"
    OPENAI_RATE_CARD_VERSION                  = ""
    OPENAI_MODEL_INPUT_MICRO_USD_PER_MILLION  = ""
    OPENAI_MODEL_OUTPUT_MICRO_USD_PER_MILLION = ""
    PLAN_BASIC_ARTICLES_PER_MONTH             = "3"
    PLAN_BASIC_CHATS_PER_MONTH                = "15"
    PLAN_BASIC_SENTENCES_PER_ARTICLE          = "50"
    PLAN_BASIC_SOURCE_TOKENS_PER_ARTICLE      = "12000"
    PLAN_BASIC_COST_MICRO_USD_PER_MONTH       = "200000"
    PLAN_BASIC_TOKENS_PER_MONTH               = "200000"
    PLAN_PRO_ARTICLES_PER_MONTH               = "40"
    PLAN_PRO_CHATS_PER_MONTH                  = "400"
    PLAN_PRO_SENTENCES_PER_ARTICLE            = "150"
    PLAN_PRO_SOURCE_TOKENS_PER_ARTICLE        = "36000"
    PLAN_PRO_COST_MICRO_USD_PER_MONTH         = "2500000"
    PLAN_PRO_TOKENS_PER_MONTH                 = "3000000"
    PLAN_MAX_ARTICLES_PER_MONTH               = "120"
    PLAN_MAX_CHATS_PER_MONTH                  = "1200"
    PLAN_MAX_SENTENCES_PER_ARTICLE            = "300"
    PLAN_MAX_SOURCE_TOKENS_PER_ARTICLE        = "72000"
    PLAN_MAX_COST_MICRO_USD_PER_MONTH         = "7000000"
    PLAN_MAX_TOKENS_PER_MONTH                 = "10000000"
  }

  validation {
    condition = length(setsubtract(toset(keys(var.usage_pricing_and_plan_environment)), toset([
      "OPENAI_TOKEN_ENCODING", "OPENAI_RATE_CARD_VERSION",
      "OPENAI_MODEL_INPUT_MICRO_USD_PER_MILLION",
      "OPENAI_MODEL_OUTPUT_MICRO_USD_PER_MILLION",
      "PLAN_BASIC_ARTICLES_PER_MONTH", "PLAN_BASIC_CHATS_PER_MONTH",
      "PLAN_BASIC_SENTENCES_PER_ARTICLE", "PLAN_BASIC_SOURCE_TOKENS_PER_ARTICLE",
      "PLAN_BASIC_COST_MICRO_USD_PER_MONTH", "PLAN_BASIC_TOKENS_PER_MONTH",
      "PLAN_PRO_ARTICLES_PER_MONTH", "PLAN_PRO_CHATS_PER_MONTH",
      "PLAN_PRO_SENTENCES_PER_ARTICLE", "PLAN_PRO_SOURCE_TOKENS_PER_ARTICLE",
      "PLAN_PRO_COST_MICRO_USD_PER_MONTH", "PLAN_PRO_TOKENS_PER_MONTH",
      "PLAN_MAX_ARTICLES_PER_MONTH", "PLAN_MAX_CHATS_PER_MONTH",
      "PLAN_MAX_SENTENCES_PER_ARTICLE", "PLAN_MAX_SOURCE_TOKENS_PER_ARTICLE",
      "PLAN_MAX_COST_MICRO_USD_PER_MONTH", "PLAN_MAX_TOKENS_PER_MONTH",
    ]))) == 0
    error_message = "usage_pricing_and_plan_environment only accepts documented tokenizer, rate-card, and PLAN_* entries."
  }
}

variable "lambda_memory_size" {
  description = "Lambda memory size in MB."
  type        = number
  default     = 512
}

variable "lambda_timeout" {
  description = "Lambda timeout in seconds. Note that API Gateway HTTP APIs cap the integration wait at 30 seconds regardless of this value."
  type        = number
  default     = 120
}

variable "reserved_concurrent_executions" {
  description = "Reserved concurrency for the function; caps parallel executions as a blast-radius limit. -1 leaves it uncapped."
  type        = number
  default     = -1
}

variable "worker_lambda_timeout" {
  description = "Timeout (seconds) for the async preload worker Lambda. Article analysis runs here, off the API Gateway request path, so it can exceed the 30-second integration cap. The SQS visibility timeout is derived as 6x this value."
  type        = number
  default     = 600
}

variable "worker_lambda_memory_size" {
  description = "Memory size in MB for the async preload worker Lambda."
  type        = number
  default     = 512
}

variable "log_retention_in_days" {
  description = "CloudWatch Logs retention for the Lambda log group."
  type        = number
  default     = 14
}

variable "throttling_rate_limit" {
  description = "API Gateway stage steady-state request rate limit (requests per second)."
  type        = number
  default     = 10
}

variable "throttling_burst_limit" {
  description = "API Gateway stage burst limit."
  type        = number
  default     = 20
}
