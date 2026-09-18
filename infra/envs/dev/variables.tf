variable "google_client_id" {
  description = "Google OAuth client ID for Cognito federation."
  type        = string
}

variable "google_client_secret" {
  description = "Google OAuth client secret for Cognito federation."
  type        = string
  sensitive   = true
}

variable "auth_callback_urls" {
  description = "Allowed Cognito callback URLs."
  type        = list(string)
  default     = ["http://localhost:13000/auth/callback"]
}

variable "auth_logout_urls" {
  description = "Allowed Cognito logout URLs."
  type        = list(string)
  default     = ["http://localhost:13000/auth/logout"]
}

variable "cognito_domain_prefix" {
  description = "Optional Cognito hosted UI domain prefix for dev."
  type        = string
  default     = null
}
