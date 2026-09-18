# Single-table DynamoDB store for the reading-assistant backend.
# The application uses a generic pk/sk key schema and serializes each
# domain document into a single "document" attribute, so no GSIs are
# required today. On-demand capacity keeps idle cost at zero.
resource "aws_dynamodb_table" "this" {
  name         = "${var.project}-${var.environment}-reading-assistant"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  deletion_protection_enabled = var.deletion_protection_enabled

  point_in_time_recovery {
    enabled = var.point_in_time_recovery_enabled
  }

  # Usage replay records write a numeric epoch value here. DynamoDB removes
  # expired private replay payloads asynchronously without application scans.
  ttl {
    attribute_name = "expires_at_epoch"
    enabled        = true
  }
}

# --- Preload content bucket -----------------------------------------------
# A preloaded article's raw extracted text is a submit -> worker handoff
# payload (see backend/storage/preload_content_store.py):
# the API writes it here, the worker reads it once and deletes it. It is kept
# out of the DynamoDB record so it does not linger and does not push the item
# toward the 400 KB limit. The account-id suffix keeps the name globally
# unique (S3 bucket names are global) while staying under the 63-char limit.
data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "preload_content" {
  bucket = "${var.project}-${var.environment}-reading-assistant-preload-content-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "preload_content" {
  bucket = aws_s3_bucket.preload_content.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "preload_content" {
  bucket = aws_s3_bucket.preload_content.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "preload_content" {
  bucket = aws_s3_bucket.preload_content.id

  versioning_configuration {
    status = "Disabled"
  }
}

# The content is transient: the worker deletes each object as it consumes it,
# and this rule expires any straggler (a job that never ran, an orphaned
# payload) after one day so nothing accumulates.
resource "aws_s3_bucket_lifecycle_configuration" "preload_content" {
  bucket = aws_s3_bucket.preload_content.id

  rule {
    id     = "expire-preload-content"
    status = "Enabled"

    filter {}

    expiration {
      days = 1
    }
  }
}
