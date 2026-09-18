mock_provider "aws" {}

variables {
  project                    = "provider-guard-test"
  environment                = "prod"
  lambda_zip_path            = "${path.module}/tests/fixtures/lambda-package.fixture"
  table_name                 = "provider-guard-test-table"
  table_arn                  = "arn:aws:dynamodb:ap-northeast-1:123456789012:table/provider-guard-test-table"
  preload_content_bucket_name = "provider-guard-test-preload-content"
  preload_content_bucket_arn  = "arn:aws:s3:::provider-guard-test-preload-content"
  secret_parameter_names = {
    OPENAI_API_KEY         = "/provider-guard-test/prod/OPENAI_API_KEY"
    STRIPE_SECRET_KEY      = "/provider-guard-test/prod/STRIPE_SECRET_KEY"
    STRIPE_WEBHOOK_SECRET  = "/provider-guard-test/prod/STRIPE_WEBHOOK_SECRET"
  }
  secret_parameter_arns = {
    OPENAI_API_KEY         = "arn:aws:ssm:ap-northeast-1:123456789012:parameter/provider-guard-test/prod/OPENAI_API_KEY"
    STRIPE_SECRET_KEY      = "arn:aws:ssm:ap-northeast-1:123456789012:parameter/provider-guard-test/prod/STRIPE_SECRET_KEY"
    STRIPE_WEBHOOK_SECRET  = "arn:aws:ssm:ap-northeast-1:123456789012:parameter/provider-guard-test/prod/STRIPE_WEBHOOK_SECRET"
  }
  google_oauth_client_id = "provider-guard-test-google-client"
  stripe_price_id_pro    = "price_provider_guard_pro"
  stripe_price_id_max    = "price_provider_guard_max"
}

run "rejects_mock_auth_provider_in_prod" {
  command = plan

  variables {
    auth_provider = "mock"
  }

  expect_failures = [var.auth_provider]
}

run "rejects_mock_billing_provider_in_prod" {
  command = plan

  variables {
    billing_provider = "mock"
  }

  expect_failures = [var.billing_provider]
}

run "rejects_auth_override_from_extra_environment" {
  command = plan

  variables {
    extra_environment = {
      AUTH_PROVIDER = "mock"
    }
  }

  expect_failures = [var.extra_environment]
}

run "rejects_billing_override_from_extra_environment" {
  command = plan

  variables {
    extra_environment = {
      BILLING_PROVIDER = "mock"
    }
  }

  expect_failures = [var.extra_environment]
}

run "rejects_storage_override_from_extra_environment" {
  command = plan

  variables {
    extra_environment = {
      STORAGE_BACKEND = "json"
    }
  }

  expect_failures = [var.extra_environment]
}

run "rejects_matching_auth_override_from_extra_environment" {
  command = plan

  variables {
    extra_environment = {
      AUTH_PROVIDER = "google"
    }
  }

  expect_failures = [var.extra_environment]
}

run "rejects_auth_override_from_pricing_environment" {
  command = plan

  variables {
    usage_pricing_and_plan_environment = {
      AUTH_PROVIDER = "mock"
    }
  }

  expect_failures = [var.usage_pricing_and_plan_environment]
}

run "rejects_billing_override_from_pricing_environment" {
  command = plan

  variables {
    usage_pricing_and_plan_environment = {
      BILLING_PROVIDER = "mock"
    }
  }

  expect_failures = [var.usage_pricing_and_plan_environment]
}

run "rejects_storage_override_from_pricing_environment" {
  command = plan

  variables {
    usage_pricing_and_plan_environment = {
      STORAGE_BACKEND = "json"
    }
  }

  expect_failures = [var.usage_pricing_and_plan_environment]
}

run "rejects_matching_auth_override_from_pricing_environment" {
  command = plan

  variables {
    usage_pricing_and_plan_environment = {
      AUTH_PROVIDER = "google"
    }
  }

  expect_failures = [var.usage_pricing_and_plan_environment]
}

run "accepts_documented_pricing_and_nonreserved_extra_environment" {
  command = plan

  variables {
    extra_environment = {
      LOG_LEVEL = "INFO"
    }
    usage_pricing_and_plan_environment = {
      OPENAI_TOKEN_ENCODING                    = "o200k_base"
      OPENAI_RATE_CARD_VERSION                 = "provider-guard-test-v1"
      OPENAI_MODEL_INPUT_MICRO_USD_PER_MILLION  = "150000"
      OPENAI_MODEL_OUTPUT_MICRO_USD_PER_MILLION = "600000"
      PLAN_BASIC_ARTICLES_PER_MONTH            = "4"
    }
  }

  assert {
    condition = (
      aws_lambda_function.this.environment[0].variables["STORAGE_BACKEND"] == "dynamodb" &&
      aws_lambda_function.this.environment[0].variables["AUTH_PROVIDER"] == "google" &&
      aws_lambda_function.this.environment[0].variables["BILLING_PROVIDER"] == "stripe" &&
      aws_lambda_function.this.environment[0].variables["LOG_LEVEL"] == "INFO" &&
      aws_lambda_function.this.environment[0].variables["OPENAI_RATE_CARD_VERSION"] == "provider-guard-test-v1"
    )
    error_message = "The API Lambda environment did not retain protected provider settings and accepted overlays."
  }

  assert {
    condition = (
      aws_lambda_function.worker.environment[0].variables["STORAGE_BACKEND"] == "dynamodb" &&
      aws_lambda_function.worker.environment[0].variables["AUTH_PROVIDER"] == "google" &&
      aws_lambda_function.worker.environment[0].variables["BILLING_PROVIDER"] == "stripe" &&
      aws_lambda_function.worker.environment[0].variables["LOG_LEVEL"] == "INFO" &&
      aws_lambda_function.worker.environment[0].variables["OPENAI_RATE_CARD_VERSION"] == "provider-guard-test-v1"
    )
    error_message = "The worker Lambda environment did not retain protected provider settings and accepted overlays."
  }
}
