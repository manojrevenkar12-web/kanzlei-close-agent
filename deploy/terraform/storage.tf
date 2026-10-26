data "aws_caller_identity" "current" {}

# Documents exactly as they arrived (XRechnung XML, ZUGFeRD, PDF) and every DATEV export.
# Object Lock in compliance mode makes the GoBD retention a property of the bucket, not of the code:
# an object cannot be overwritten or deleted before its retention ends, by anyone.
resource "aws_s3_bucket" "documents" {
  bucket              = "${var.name}-${var.environment}-documents-${data.aws_caller_identity.current.account_id}"
  object_lock_enabled = true
}

resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_object_lock_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    default_retention {
      mode  = "COMPLIANCE"
      years = var.document_retention_years
    }
  }
  depends_on = [aws_s3_bucket_versioning.documents]
}

resource "aws_kms_key" "documents" {
  description             = "Client documents of ${var.name}-${var.environment}"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.documents.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket                  = aws_s3_bucket.documents.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_policy" "documents" {
  bucket = aws_s3_bucket.documents.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "TLSOnly"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.documents.arn, "${aws_s3_bucket.documents.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

# After retention ends, old versions go to cheaper storage first and are removed by people, not rules.
resource "aws_s3_bucket_lifecycle_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    id     = "archive"
    status = "Enabled"
    filter {}
    transition {
      days          = 400
      storage_class = "GLACIER_IR"
    }
  }
}

resource "aws_ecr_repository" "repo" {
  for_each             = toset(["api", "web", "tools"])
  name                 = "${var.name}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "repo" {
  for_each   = aws_ecr_repository.repo
  repository = each.value.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep the last 50 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 50 }
      action       = { type = "expire" }
    }]
  })
}
