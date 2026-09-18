variable "lambda_zip_path" {
  description = "Path to the pre-built Lambda zip. Build it with backend/scripts/build_lambda.sh and run terraform from this directory."
  type        = string
  default     = "../../../backend/dist/reading-assistant-lambda.zip"
}

variable "auth_provider" {
  description = "Identity provider: \"google\" or \"mock\". Prod only accepts \"google\"."
  type        = string
  default     = "google"
}

variable "google_oauth_client_id" {
  description = "Google OAuth client ID used to verify Google ID tokens."
  type        = string
  sensitive   = true
}

variable "billing_provider" {
  description = "Billing provider: \"stripe\" or \"mock\". Prod only accepts \"stripe\"."
  type        = string
  default     = "stripe"
}

variable "stripe_price_id_pro" {
  description = "Stripe price ID for the pro plan."
  type        = string
  default     = ""
  sensitive   = true
}

variable "stripe_price_id_max" {
  description = "Stripe price ID for the max plan."
  type        = string
  default     = ""
  sensitive   = true
}

variable "allowed_origins" {
  description = "Extra CORS origins (ALLOWED_ORIGINS). chrome-extension:// origins are always allowed by the app itself."
  type        = list(string)
  default     = []
}

variable "app_extra_environment" {
  description = "Additional non-secret app environment variables that are not reserved usage settings."
  type        = map(string)
  default     = {}
  sensitive   = true
}

variable "usage_reservation_enabled" {
  description = "Enable atomic usage enforcement after staging verification."
  type        = bool
  default     = false
}

variable "usage_reservation_ttl_seconds" {
  type    = number
  default = 900
}

variable "sync_result_ttl_seconds" {
  type    = number
  default = 86400
}

variable "sync_result_max_bytes" {
  type    = number
  default = 65536
}

variable "sync_result_cleanup_batch_size" {
  type    = number
  default = 100
}

variable "sync_execution_lease_seconds" {
  type    = number
  default = 120
}

variable "sync_execution_wait_seconds" {
  type    = number
  default = 2
}

variable "preload_worker_lease_seconds" {
  type    = number
  default = 900
}

variable "openai_max_input_tokens_per_call" {
  type    = number
  default = 128000
}

variable "max_sentence_split_agent_turns" {
  type    = number
  default = 2
}

variable "usage_pricing_and_plan_environment" {
  description = "Pinned tokenizer, rate card, model rates, and plan limits."
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
}

variable "alert_email" {
  description = "Email address for budget and abuse alarms."
  type        = string
  sensitive   = true
}

variable "monthly_budget_limit_usd" {
  description = "Monthly AWS cost budget (USD) acting as the blast-radius cap."
  type        = number
  default     = 10
}

variable "lambda_invocations_hourly_threshold" {
  description = "Alarm when the backend Lambda exceeds this many invocations per hour."
  type        = number
  default     = 1000
}

variable "lambda_memory_size" {
  description = "Lambda memory size in MB."
  type        = number
  default     = 512
}

variable "lambda_timeout" {
  description = "API Lambda timeout in seconds. It only extracts and enqueues now, so it stays well under API Gateway's 30-second integration cap."
  type        = number
  default     = 120
}

variable "worker_lambda_timeout" {
  description = "Async preload worker Lambda timeout in seconds (runs article analysis off the request path)."
  type        = number
  default     = 600
}

variable "worker_lambda_memory_size" {
  description = "Async preload worker Lambda memory size in MB."
  type        = number
  default     = 512
}

variable "reserved_concurrent_executions" {
  description = "Reserved concurrency cap for the backend Lambda (-1 = uncapped)."
  type        = number
  default     = 5
}

variable "log_retention_in_days" {
  description = "CloudWatch Logs retention in days."
  type        = number
  default     = 14
}

variable "throttling_rate_limit" {
  description = "API Gateway steady-state rate limit (requests per second)."
  type        = number
  default     = 10
}

variable "throttling_burst_limit" {
  description = "API Gateway burst limit."
  type        = number
  default     = 20
}
