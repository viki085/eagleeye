# One CloudWatch dashboard for the run: tasks per service, answers in progress, load balancer
# requests and response time, CPU. media/arch-load/export.py reads the same metrics.

locals {
  scaled = ["api", "agent-worker", "gateway", "ingest-worker"]
}

resource "aws_cloudwatch_dashboard" "this" {
  dashboard_name = local.name
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6
        properties = {
          title   = "Running tasks per service"
          region  = var.region
          stat    = "Average"
          period  = 60
          metrics = [for s in local.scaled : ["ECS/ContainerInsights", "RunningTaskCount", "ClusterName", local.name, "ServiceName", s]]
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6
        properties = {
          title   = "Answers in progress"
          region  = var.region
          stat    = "Average"
          period  = 60
          metrics = [["EagleEye/LoadTest", "ActiveAnswers"]]
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 12, height = 6
        properties = {
          title  = "Load balancer: requests and errors"
          region = var.region
          stat   = "Sum"
          period = 60
          metrics = [
            ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", aws_lb.api.arn_suffix],
            ["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "LoadBalancer", aws_lb.api.arn_suffix],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 6, width = 12, height = 6
        properties = {
          title   = "CPU per service (%)"
          region  = var.region
          stat    = "Average"
          period  = 60
          metrics = [for s in local.scaled : ["AWS/ECS", "CPUUtilization", "ClusterName", local.name, "ServiceName", s]]
        }
      },
    ]
  })
}
