# EagleEye demo environment on AWS (Phase 7B, docs/phase7-cloud-plan.md).
#
# Always present and near-zero cost while the demo machine is stopped: network, image registry,
# buckets, settings in Parameter Store, the demo machine (stopped by default), CloudFront, the
# wake function, the analysis sandbox function, the nightly stop, budget alerts and the GitHub
# deploy role. Secrets (OpenAI, Supabase, Clerk...) are NOT managed here: scripts/cloud_env.py
# writes them to Parameter Store from a git-ignored file, so they never enter Terraform state.
#
#   terraform init -backend-config=backend.hcl
#   terraform plan -out=base.tfplan && terraform apply base.tfplan

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 6.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.7" }
    random  = { source = "hashicorp/random", version = "~> 3.6" }
  }
  backend "s3" {}
}

provider "aws" {
  region  = var.region
  profile = var.profile
  default_tags {
    tags = { Project = "eagleeye", ManagedBy = "terraform", Stack = "base" }
  }
}

data "aws_caller_identity" "me" {}
data "aws_partition" "current" {}

locals {
  name       = "eagleeye"
  account_id = data.aws_caller_identity.me.account_id
  # SSM paths: the machine reads everything under env/ into its .env file at every boot
  ssm_root = "/eagleeye/demo"
  ssm_env  = "/eagleeye/demo/env"
}
