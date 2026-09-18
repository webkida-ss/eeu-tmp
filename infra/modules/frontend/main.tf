locals {
  project_name = "vicente-calderon"
  name_prefix  = "${local.project_name}-${var.environment}-frontend"

  tags = {
    Project     = local.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

