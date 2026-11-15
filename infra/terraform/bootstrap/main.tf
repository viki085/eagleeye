# One-time: the S3 bucket that holds the state of infra/terraform/base (Phase 7B).
# Its own state stays local (terraform.tfstate here, git-ignored): it is one bucket.
#
#   cd infra/terraform/bootstrap
#   terraform init && terraform apply
#   → copy the printed backend settings into ../base/backend.hcl

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "profile" {
  description = "AWS CLI profile (aws login --profile ...)"
  type        = string
  default     = "eagleeye"
}

provider "aws" {
  region  = var.region
  profile = var.profile
  default_tags {
    tags = { Project = "eagleeye", ManagedBy = "terraform", Stack = "bootstrap" }
  }
}

data "aws_caller_identity" "me" {}

resource "aws_s3_bucket" "state" {
  bucket = "eagleeye-tfstate-${data.aws_caller_identity.me.account_id}"
  lifecycle { prevent_destroy = true }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.id
  rule { object_ownership = "BucketOwnerEnforced" }
}

resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    id     = "old-state-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration { noncurrent_days = 90 }
  }
}

resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "TlsOnly"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

output "backend_hcl" {
  description = "Contents for infra/terraform/base/backend.hcl"
  value       = <<-EOT
    bucket       = "${aws_s3_bucket.state.id}"
    key          = "base/terraform.tfstate"
    region       = "${var.region}"
    profile      = "${var.profile}"
    use_lockfile = true
    encrypt      = true
  EOT
}
