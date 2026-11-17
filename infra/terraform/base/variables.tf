variable "region" {
  type    = string
  default = "us-east-1"
}

variable "profile" {
  description = "AWS CLI profile (aws login --profile ...)"
  type        = string
  default     = "eagleeye"
}

variable "alert_email" {
  description = "Where budget alerts are sent (set in terraform.tfvars, which is git-ignored)"
  type        = string
}

variable "github_repo" {
  description = "owner/name of the GitHub repo whose main branch may deploy"
  type        = string
}

variable "github_oidc_subject_prefix" {
  description = <<-EOT
    The repo part of GitHub's OIDC subject. Repos with immutable subjects use
    "repo:<owner>@<owner id>/<name>@<repo id>"; see
    gh api repos/OWNER/REPO/actions/oidc/customization/sub. Empty = "repo:<github_repo>".
  EOT
  type        = string
  default     = ""
}

variable "web_origin" {
  description = "The web app's address (Vercel), for CORS and Clerk token checks"
  type        = string
  default     = "http://localhost:3000"
}

variable "demo_instance_type" {
  description = "Free-plan types only: c7i-flex.large (4 GB) or m7i-flex.large (8 GB)"
  type        = string
  default     = "m7i-flex.large"
}

variable "demo_disk_gb" {
  type    = number
  default = 20
}

variable "idle_minutes" {
  description = "The demo machine stops itself after this long with no requests"
  type        = number
  default     = 30
}

variable "daily_runtime_cap_hours" {
  description = "The wake function refuses to start the machine beyond this much running time per UTC day"
  type        = number
  default     = 12
}

variable "nightly_stop_cron" {
  description = "Safety stop, EventBridge Scheduler cron in UTC"
  type        = string
  default     = "cron(0 3 * * ? *)"
}

variable "sandbox_image_tag" {
  description = "Tag of the sandbox image in ECR. Empty until the first image is pushed: the function is created only once it exists."
  type        = string
  default     = ""
}

variable "sandbox_memory_mb" {
  description = "Above the notebook runs' 2 GB memory limit (set inside the function) plus overhead"
  type        = number
  default     = 3008
}

variable "sandbox_timeout_s" {
  type    = number
  default = 150
}

variable "budget_limit_usd" {
  description = "Monthly budget the alerts are measured against"
  type        = number
  default     = 100
}
