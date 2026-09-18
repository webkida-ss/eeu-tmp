variable "environment" {
  description = "Deployment environment name."
  type        = string
}

variable "worker_image_uri" {
  description = "Optional container image URI for the personalization worker Lambda."
  type        = string
  default     = null
}

