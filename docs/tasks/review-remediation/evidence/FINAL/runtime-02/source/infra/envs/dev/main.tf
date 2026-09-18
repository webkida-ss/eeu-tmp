locals {
  project     = "english"
  environment = "dev"
}

module "data" {
  source = "../../modules/reading-assistant-data"

  project     = local.project
  environment = local.environment

  # Dev keeps storage cost at the floor: no PITR, no deletion protection.
  point_in_time_recovery_enabled = false
  deletion_protection_enabled    = false
}

module "config" {
  source = "../../modules/reading-assistant-config"

  project     = local.project
  environment = local.environment
}

module "api" {
  source = "../../modules/reading-assistant-api"

  project     = local.project
  environment = local.environment

  lambda_zip_path = var.lambda_zip_path

  table_name                  = module.data.table_name
  table_arn                   = module.data.table_arn
  preload_content_bucket_name = module.data.preload_content_bucket_name
  preload_content_bucket_arn  = module.data.preload_content_bucket_arn
  secret_parameter_names      = module.config.secret_parameter_names
  secret_parameter_arns       = module.config.secret_parameter_arns

  auth_provider          = var.auth_provider
  google_oauth_client_id = var.google_oauth_client_id
  billing_provider       = var.billing_provider
  stripe_price_id_pro    = var.stripe_price_id_pro
  stripe_price_id_max    = var.stripe_price_id_max

  allowed_origins   = var.allowed_origins
  extra_environment = var.app_extra_environment

  usage_reservation_enabled          = var.usage_reservation_enabled
  usage_reservation_ttl_seconds      = var.usage_reservation_ttl_seconds
  sync_result_ttl_seconds            = var.sync_result_ttl_seconds
  sync_result_max_bytes              = var.sync_result_max_bytes
  sync_result_cleanup_batch_size     = var.sync_result_cleanup_batch_size
  sync_execution_lease_seconds       = var.sync_execution_lease_seconds
  sync_execution_wait_seconds        = var.sync_execution_wait_seconds
  preload_worker_lease_seconds       = var.preload_worker_lease_seconds
  openai_max_input_tokens_per_call   = var.openai_max_input_tokens_per_call
  max_sentence_split_agent_turns     = var.max_sentence_split_agent_turns
  usage_pricing_and_plan_environment = var.usage_pricing_and_plan_environment

  lambda_memory_size             = var.lambda_memory_size
  lambda_timeout                 = var.lambda_timeout
  reserved_concurrent_executions = var.reserved_concurrent_executions
  worker_lambda_timeout          = var.worker_lambda_timeout
  worker_lambda_memory_size      = var.worker_lambda_memory_size
  log_retention_in_days          = var.log_retention_in_days
  throttling_rate_limit          = var.throttling_rate_limit
  throttling_burst_limit         = var.throttling_burst_limit
}

module "alerting" {
  source = "../../modules/reading-assistant-alerting"

  project     = local.project
  environment = local.environment

  alert_email                         = var.alert_email
  monthly_budget_limit_usd            = var.monthly_budget_limit_usd
  lambda_function_name                = module.api.lambda_function_name
  lambda_invocations_hourly_threshold = var.lambda_invocations_hourly_threshold
}
