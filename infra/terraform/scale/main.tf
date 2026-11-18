# Scale mode (Phase 7C): EagleEye on ECS Fargate with autoscaling, for the load test only.
# Created for the test and destroyed straight after (terraform destroy). Everything it needs
# lives here, so nothing is left behind and the demo is never touched:
#   - a second public subnet (a load balancer needs two availability zones)
#   - ECS services: api, agent-worker, ingest-worker, gateway (the app image) + redis, qdrant,
#     an app database (Supabase Postgres with the migrations) and the Grand Line warehouse
#   - a load balancer behind its own CloudFront (HTTPS on *.cloudfront.net, nothing cached)
#   - autoscaling: API on CPU, agent workers on answers in progress per worker
#   - a k6 task definition, a CloudWatch dashboard, and a stop timer that scales everything to
#     zero after var.max_hours in case the destroy is forgotten
#
#   terraform init -backend-config=backend.hcl   (key = "scale/terraform.tfstate")
#   terraform plan -out=scale.tfplan && terraform apply scale.tfplan
#   ... test ...
#   terraform destroy

terraform {
  required_version = ">= 1.9"
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 6.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.7" }
    random  = { source = "hashicorp/random", version = "~> 3.6" }
  }
  backend "s3" {}
}

provider "aws" {
  region  = var.region
  profile = var.aws_profile
  default_tags {
    tags = { Project = "eagleeye", ManagedBy = "terraform", Stack = "scale" }
  }
}

data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" { state = "available" }

# the base stack (network, image registry, buckets, sandbox function) from its saved state
data "terraform_remote_state" "base" {
  backend = "s3"
  config = {
    bucket  = var.state_bucket
    key     = "base/terraform.tfstate"
    region  = var.region
    profile = var.aws_profile
  }
}

data "aws_vpc" "main" {
  filter {
    name   = "tag:Name"
    values = ["eagleeye"]
  }
}

data "aws_subnet" "public_a" {
  filter {
    name   = "tag:Name"
    values = ["eagleeye-public"]
  }
}

data "aws_route_table" "public" {
  subnet_id = data.aws_subnet.public_a.id
}

data "aws_ssm_parameter" "image_tag" {
  name = "/eagleeye/demo/image_tag"
}

locals {
  name      = "eagleeye-lt"
  ns        = "eagleeye-lt.local" # internal service names: <service>.eagleeye-lt.local
  account   = data.aws_caller_identity.current.account_id
  ecr       = "${local.account}.dkr.ecr.${var.region}.amazonaws.com/eagleeye"
  app_image = "${local.ecr}:${coalesce(var.app_image_tag, nonsensitive(data.aws_ssm_parameter.image_tag.value))}"
  buckets   = data.terraform_remote_state.base.outputs.buckets
  subnets   = [data.aws_subnet.public_a.id, aws_subnet.public_b.id]
}
