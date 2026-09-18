variable "environment" {
  description = "Deployment environment name."
  type        = string
}

variable "google_client_id" {
  description = "Google OAuth client ID used by Cognito federation."
  type        = string
}

variable "google_client_secret" {
  description = "Google OAuth client secret used by Cognito federation."
  type        = string
  sensitive   = true
}

variable "callback_urls" {
  description = "Allowed OAuth callback URLs for the Cognito app client."
  type        = list(string)
}

variable "logout_urls" {
  description = "Allowed OAuth logout URLs for the Cognito app client."
  type        = list(string)
}

variable "cognito_domain_prefix" {
  description = "Optional Cognito hosted UI domain prefix. Must be unique in the AWS region."
  type        = string
  default     = null
}
