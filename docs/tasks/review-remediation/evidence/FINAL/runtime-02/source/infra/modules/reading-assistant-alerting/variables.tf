variable "project" {
  description = "Project prefix used in resource names (e.g. \"english\")."
  type        = string
}

variable "environment" {
  description = "Environment name used in resource names (e.g. \"dev\", \"prod\")."
  type        = string
}

variable "alert_email" {
  description = "Email address that receives budget and alarm notifications."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+$", var.alert_email))
    error_message = "alert_email must be a valid email address."
  }
}

variable "monthly_budget_limit_usd" {
  description = "Monthly AWS cost budget in USD. Notifications fire at 50/80/100% of this amount."
  type        = number
}

variable "lambda_function_name" {
  description = "Name of the backend Lambda function to monitor."
  type        = string
}

variable "lambda_invocations_hourly_threshold" {
  description = "Alarm when the backend Lambda exceeds this many invocations in one hour."
  type        = number
}
