# Safety stop: var.max_hours after apply, one-time schedules scale every service to zero (the
# autoscaled ones by pinning their range to 0..0, so autoscaling can't start them again).
# The load balancer and CloudFront keep costing a few cents an hour until `terraform destroy`.

locals {
  stop_at = formatdate("YYYY-MM-DD'T'hh:mm:ss", timeadd(timestamp(), "${var.max_hours}h"))
}

resource "aws_iam_role" "stop" {
  name = "${local.name}-stop"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "scheduler.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "stop" {
  name = "scale-to-zero"
  role = aws_iam_role.stop.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecs:UpdateService"]
        Resource = [for s in aws_ecs_service.svc : s.id]
      },
      {
        Effect   = "Allow"
        Action   = ["application-autoscaling:RegisterScalableTarget", "ecs:DescribeServices", "ecs:UpdateService", "cloudwatch:DescribeAlarms", "cloudwatch:PutMetricAlarm"]
        Resource = "*"
      },
    ]
  })
}

resource "aws_scheduler_schedule" "stop_scaled" {
  for_each                     = aws_appautoscaling_target.svc
  name                         = "${local.name}-stop-${each.key}"
  schedule_expression          = "at(${local.stop_at})"
  schedule_expression_timezone = "UTC"
  action_after_completion      = "DELETE"
  flexible_time_window { mode = "OFF" }
  target {
    arn      = "arn:aws:scheduler:::aws-sdk:applicationautoscaling:registerScalableTarget"
    role_arn = aws_iam_role.stop.arn
    input = jsonencode({
      ServiceNamespace  = "ecs"
      ResourceId        = each.value.resource_id
      ScalableDimension = "ecs:service:DesiredCount"
      MinCapacity       = 0
      MaxCapacity       = 0
    })
  }
  lifecycle { ignore_changes = [schedule_expression] } # fixed at first apply
}

resource "aws_scheduler_schedule" "stop_fixed" {
  for_each                     = { for k, v in aws_ecs_service.svc : k => v if !contains(keys(aws_appautoscaling_target.svc), k) }
  name                         = "${local.name}-stop-${each.key}"
  schedule_expression          = "at(${local.stop_at})"
  schedule_expression_timezone = "UTC"
  action_after_completion      = "DELETE"
  flexible_time_window { mode = "OFF" }
  target {
    arn      = "arn:aws:scheduler:::aws-sdk:ecs:updateService"
    role_arn = aws_iam_role.stop.arn
    input = jsonencode({
      Cluster      = aws_ecs_cluster.this.name
      Service      = each.value.name
      DesiredCount = 0
    })
  }
  lifecycle { ignore_changes = [schedule_expression] }
}
