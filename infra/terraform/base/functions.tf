# Two Lambda functions:
#   wake     starts the demo machine (function URL + shared secret), keeps the daily
#            running-time cap, and does the hourly and nightly safety stops
#   sandbox  the analysis sandbox (container image), in the no-internet subnet

locals {
  sandbox_function_name = "${local.name}-sandbox"
  wake_function_name    = "${local.name}-wake"
}

# ---- wake ---------------------------------------------------------------------------------

data "archive_file" "wake" {
  type        = "zip"
  source_file = "${path.module}/lambda/wake/wake.py"
  output_path = "${path.module}/.build/wake.zip"
}

resource "aws_iam_role" "wake" {
  name = "${local.name}-wake"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "wake_logs" {
  role       = aws_iam_role.wake.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "wake" {
  name = "eagleeye-wake"
  role = aws_iam_role.wake.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "StartStopDemoMachine"
        Effect   = "Allow"
        Action   = ["ec2:StartInstances", "ec2:StopInstances"]
        Resource = aws_instance.demo.arn
      },
      {
        Sid      = "SeeDemoMachine"
        Effect   = "Allow"
        Action   = "ec2:DescribeInstances"
        Resource = "*" # DescribeInstances supports no resource-level restriction
      },
      {
        Sid      = "RunningTime"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:PutParameter"]
        Resource = aws_ssm_parameter.runtime.arn
      },
    ]
  })
}

resource "aws_lambda_function" "wake" {
  function_name    = local.wake_function_name
  role             = aws_iam_role.wake.arn
  runtime          = "python3.13"
  handler          = "wake.handler"
  filename         = data.archive_file.wake.output_path
  source_code_hash = data.archive_file.wake.output_base64sha256
  timeout          = 15
  memory_size      = 128
  environment {
    variables = {
      INSTANCE_ID   = aws_instance.demo.id
      RUNTIME_PARAM = aws_ssm_parameter.runtime.name
      DAILY_CAP_S   = tostring(var.daily_runtime_cap_hours * 3600)
      WAKE_SECRET   = random_password.wake.result
    }
  }
}

resource "aws_cloudwatch_log_group" "wake" {
  name              = "/aws/lambda/${local.wake_function_name}"
  retention_in_days = 14
}

# Public URL; the function itself checks the shared secret (the web app's server holds it).
# A wrong secret costs one ~10 ms run; the web app rate-limits its own calls per user.
resource "aws_lambda_function_url" "wake" {
  function_name      = aws_lambda_function.wake.function_name
  authorization_type = "NONE"
}

resource "aws_lambda_permission" "wake_url" {
  statement_id           = "FunctionUrlPublic"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.wake.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

# EC2 state changes keep the running-time record up to date
resource "aws_cloudwatch_event_rule" "demo_state" {
  name        = "${local.name}-demo-state"
  description = "Demo machine started or stopped"
  event_pattern = jsonencode({
    source        = ["aws.ec2"]
    "detail-type" = ["EC2 Instance State-change Notification"]
    detail        = { "instance-id" = [aws_instance.demo.id], state = ["running", "stopped"] }
  })
}

resource "aws_cloudwatch_event_target" "demo_state" {
  rule = aws_cloudwatch_event_rule.demo_state.name
  arn  = aws_lambda_function.wake.arn
}

resource "aws_lambda_permission" "demo_state" {
  statement_id  = "EventBridgeStateChange"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.wake.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.demo_state.arn
}

# Hourly cap check and the nightly safety stop
resource "aws_iam_role" "scheduler" {
  name = "${local.name}-scheduler"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } }
    }]
  })
}

resource "aws_iam_role_policy" "scheduler" {
  name = "invoke-wake"
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = aws_lambda_function.wake.arn
    }]
  })
}

resource "aws_scheduler_schedule" "wake" {
  for_each = {
    enforce      = "rate(1 hour)"
    nightly_stop = var.nightly_stop_cron
  }
  name                = "${local.name}-${replace(each.key, "_", "-")}"
  schedule_expression = each.value
  flexible_time_window { mode = "OFF" }
  target {
    arn      = aws_lambda_function.wake.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ action = each.key })
  }
}

# ---- sandbox ------------------------------------------------------------------------------
# Created once the first image is in ECR (set sandbox_image_tag). Its role can write logs and
# attach to the subnet, nothing else: inputs and outputs travel through pre-signed S3 links.

resource "aws_iam_role" "sandbox" {
  name = "${local.name}-sandbox"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "sandbox_vpc" {
  role       = aws_iam_role.sandbox.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_cloudwatch_log_group" "sandbox" {
  name              = "/aws/lambda/${local.sandbox_function_name}"
  retention_in_days = 14
}

resource "aws_lambda_function" "sandbox" {
  count         = var.sandbox_image_tag == "" ? 0 : 1
  function_name = local.sandbox_function_name
  role          = aws_iam_role.sandbox.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.this["eagleeye-sandbox-lambda"].repository_url}:${var.sandbox_image_tag}"
  architectures = ["x86_64"]
  memory_size   = var.sandbox_memory_mb
  timeout       = var.sandbox_timeout_s
  ephemeral_storage { size = 1024 }
  vpc_config {
    subnet_ids         = [aws_subnet.sandbox.id]
    security_group_ids = [aws_security_group.sandbox.id]
  }
  depends_on = [aws_cloudwatch_log_group.sandbox]
  lifecycle {
    # after creation the deploy workflow moves the function to each new image
    ignore_changes = [image_uri]
  }
}
