variable "region" {
  type    = string
  default = "us-east-1"
}

variable "aws_profile" {
  type    = string
  default = "eagleeye"
}

variable "state_bucket" {
  description = "The Terraform state bucket (same as the base stack's backend.hcl)"
  type        = string
}

variable "app_image_tag" {
  description = "App image tag (commit SHA); empty = the tag the demo runs (SSM image_tag)"
  type        = string
  default     = ""
}

variable "appdb_image_tag" {
  description = "Load-test app database image in ECR repo eagleeye (Supabase Postgres + migrations + catalog)"
  type        = string
  default     = "loadtest-appdb-1"
}

variable "warehouse_image_tag" {
  description = "Load-test warehouse image in ECR repo eagleeye (Grand Line data baked in)"
  type        = string
  default     = "loadtest-warehouse-1"
}

variable "k6_image_tag" {
  description = "Private k6 image in ECR repo eagleeye (script, question pool, tokens)"
  type        = string
  default     = "loadtest-k6-1"
}

variable "loadtest_public_key_file" {
  description = "PEM public key for synthetic users' tokens (scripts/loadtest_seed.py keys)"
  type        = string
  default     = "../../../.loadtest/public.pem"
}

variable "db_password_file" {
  description = "Password the load-test database images were built with (build-images.sh)"
  type        = string
  default     = "../../../.loadtest/db_password"
}

variable "web_origin" {
  description = "The web app address the recordings use (CORS): a local production build"
  type        = string
}

variable "max_hours" {
  description = "Safety stop: every service is scaled to zero this many hours after apply"
  type        = number
  default     = 4
}

# autoscaling bounds: 6 x 0.5 + 12 x 1 + fixed services + k6 (4) stays inside the 30 vCPU quota
variable "api_max" {
  type    = number
  default = 6
}

variable "agent_max" {
  type    = number
  default = 12
}

variable "answers_per_worker" {
  description = "Target answers in progress per agent worker (each runs 8 at once)"
  type        = number
  default     = 5
}
