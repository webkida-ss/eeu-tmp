variable "project" {
  description = "Project prefix used in resource names (e.g. \"english\")."
  type        = string
}

variable "environment" {
  description = "Environment name used in resource names (e.g. \"dev\", \"prod\")."
  type        = string
}

variable "point_in_time_recovery_enabled" {
  description = "Enable point-in-time recovery. Recommended in prod only (PITR is billed per GB stored)."
  type        = bool
  default     = false
}

variable "deletion_protection_enabled" {
  description = "Protect the table from accidental deletion. Recommended in prod."
  type        = bool
  default     = false
}
