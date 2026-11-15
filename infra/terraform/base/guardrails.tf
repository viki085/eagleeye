# Budget alerts and the GitHub deploy role.

resource "aws_budgets_budget" "monthly" {
  name         = "${local.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # credits would hide the real spend: alert on usage before credits are applied
  cost_types {
    include_credit = false
    include_refund = false
  }

  dynamic "notification" {
    for_each = [25, 50, 75]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.alert_email]
    }
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}

# ---- GitHub Actions deploys without stored AWS keys (OIDC) ----------------------------------

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

resource "aws_iam_role" "deploy" {
  name = "${local.name}-github-deploy"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          # only the main branch of this repo
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repo}:ref:refs/heads/main"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "deploy" {
  name = "eagleeye-deploy"
  role = aws_iam_role.deploy.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "EcrLogin"
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*"
      },
      {
        Sid    = "EcrPush"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer", "ecr:DescribeImages",
        ]
        Resource = [for r in aws_ecr_repository.this : r.arn]
      },
      {
        Sid      = "RecordImageTag"
        Effect   = "Allow"
        Action   = ["ssm:PutParameter", "ssm:GetParameter"]
        Resource = aws_ssm_parameter.image_tag.arn
      },
      {
        Sid      = "UpdateSandbox"
        Effect   = "Allow"
        Action   = ["lambda:UpdateFunctionCode", "lambda:GetFunction"]
        Resource = "arn:${data.aws_partition.current.partition}:lambda:${var.region}:${local.account_id}:function:${local.sandbox_function_name}"
      },
      {
        Sid      = "UploadBundle"
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.this["deploy"].arn}/bundle/*"
      },
      {
        Sid      = "SeeDemoMachine"
        Effect   = "Allow"
        Action   = "ec2:DescribeInstances"
        Resource = "*"
      },
      {
        Sid    = "RedeployRunningMachine"
        Effect = "Allow"
        Action = "ssm:SendCommand"
        Resource = [
          aws_instance.demo.arn,
          "arn:${data.aws_partition.current.partition}:ssm:${var.region}::document/AWS-RunShellScript",
        ]
      },
    ]
  })
}
