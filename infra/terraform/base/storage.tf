# Buckets (all private, encrypted, TLS only):
#   docs       uploaded documents and data files     (DOCS_BUCKET)
#   artifacts  result tables, charts, notebooks       (ARTIFACTS_BUCKET)
#   transfer   sandbox inputs/outputs in transit; expire after a day (SANDBOX_TRANSFER_BUCKET)
#   deploy     the Compose bundle the demo machine pulls at boot

locals {
  buckets = {
    docs      = { expire_days = 0 }
    artifacts = { expire_days = 0 }
    transfer  = { expire_days = 1 }
    deploy    = { expire_days = 0 }
  }
}

resource "aws_s3_bucket" "this" {
  for_each = local.buckets
  bucket   = "${local.name}-${each.key}-${local.account_id}"
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each                = aws_s3_bucket.this
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  rule { object_ownership = "BucketOwnerEnforced" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_policy" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "TlsOnly"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [each.value.arn, "${each.value.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
  depends_on = [aws_s3_bucket_public_access_block.this]
}

resource "aws_s3_bucket_lifecycle_configuration" "transfer" {
  bucket = aws_s3_bucket.this["transfer"].id
  rule {
    id     = "expire-in-transit"
    status = "Enabled"
    filter {}
    expiration { days = local.buckets.transfer.expire_days }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
}

# the Compose bundle: what the machine needs from the repo besides the image
locals {
  bundle_files = {
    "infra/cloud/compose.demo.yml"       = "${path.module}/../../cloud/compose.demo.yml"
    "infra/cloud/boot.sh"                = "${path.module}/../../cloud/boot.sh"
    "infra/warehouse/init/01_schema.sql" = "${path.module}/../../warehouse/init/01_schema.sql"
    "infra/warehouse/init/02_roles.sql"  = "${path.module}/../../warehouse/init/02_roles.sql"
  }
}

resource "aws_s3_object" "bundle" {
  for_each = local.bundle_files
  bucket   = aws_s3_bucket.this["deploy"].id
  key      = "bundle/${each.key}"
  source   = each.value
  etag     = filemd5(each.value)
}

# ---- container registry ---------------------------------------------------------------------

resource "aws_ecr_repository" "this" {
  for_each             = toset(["eagleeye", "eagleeye-sandbox-lambda"])
  name                 = each.key
  image_tag_mutability = "IMMUTABLE" # tags are commit SHAs
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration { encryption_type = "AES256" }
}

resource "aws_ecr_lifecycle_policy" "this" {
  for_each   = aws_ecr_repository.this
  repository = each.value.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 10 }
      action       = { type = "expire" }
    }]
  })
}
