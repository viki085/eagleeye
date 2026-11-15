# The demo machine's settings. At every boot it reads every parameter under /eagleeye/demo/env/
# into its .env file (name = the last path segment).
#
# Managed here: values that are not secrets, plus internal secrets Terraform generates (they
# live in the encrypted, private state bucket and are never output).
# NOT managed here: your own keys (OpenAI, Supabase, Qdrant, Clerk, SMTP). scripts/cloud_env.py
# writes those from a git-ignored .env.cloud, so they never enter Terraform state.

resource "random_password" "origin_verify" {
  length  = 48
  special = false
}

resource "random_password" "gateway_hmac" {
  length  = 48
  special = false
}

resource "random_password" "warehouse_admin" {
  length  = 32
  special = false
}

resource "random_password" "warehouse_ro" {
  length  = 32
  special = false
}

resource "random_password" "wake" {
  length  = 48
  special = false
}

locals {
  plain_settings = {
    APP_ENV                 = "demo"
    LOG_FORMAT              = "json"
    AWS_REGION              = var.region
    WEB_ORIGIN              = var.web_origin
    DOCS_BUCKET             = aws_s3_bucket.this["docs"].id
    ARTIFACTS_BUCKET        = aws_s3_bucket.this["artifacts"].id
    SANDBOX_TRANSFER_BUCKET = aws_s3_bucket.this["transfer"].id
    SANDBOX_BACKEND         = "lambda"
    SANDBOX_LAMBDA_FUNCTION = local.sandbox_function_name
    SANDBOX_TIMEOUT_S       = "60"
    # Supabase's free pooler allows few connections: small pools per process
    DB_POOL_MAX_API     = "5"
    DB_POOL_MAX_WORKER  = "5"
    DB_POOL_MAX_GATEWAY = "3"
  }
  generated_secrets = {
    ORIGIN_VERIFY_SECRET     = random_password.origin_verify.result
    GATEWAY_HMAC_SECRET      = random_password.gateway_hmac.result
    WAREHOUSE_ADMIN_PASSWORD = random_password.warehouse_admin.result
    WAREHOUSE_RO_PASSWORD    = random_password.warehouse_ro.result
    WAREHOUSE_DSN            = "postgresql://eagleeye_ro:${random_password.warehouse_ro.result}@warehouse:5432/warehouse"
  }
}

resource "aws_ssm_parameter" "plain" {
  for_each = local.plain_settings
  name     = "${local.ssm_env}/${each.key}"
  type     = "String"
  value    = each.value
}

resource "aws_ssm_parameter" "generated" {
  for_each = nonsensitive(toset(keys(local.generated_secrets)))
  name     = "${local.ssm_env}/${each.key}"
  type     = "SecureString"
  value    = local.generated_secrets[each.key]
}

# Set by the deploy pipeline; the machine runs this image tag. "none" until the first deploy.
resource "aws_ssm_parameter" "image_tag" {
  name  = "${local.ssm_root}/image_tag"
  type  = "String"
  value = "none"
  lifecycle { ignore_changes = [value] }
}

# Running time today, kept by the wake function (for the daily cap)
resource "aws_ssm_parameter" "runtime" {
  name  = "${local.ssm_root}/runtime"
  type  = "String"
  value = jsonencode({ day = "", seconds = 0, started_at = 0 })
  lifecycle { ignore_changes = [value] }
}
