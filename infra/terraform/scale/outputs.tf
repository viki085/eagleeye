# Nothing secret is output.

output "api_url" {
  description = "NEXT_PUBLIC_API_URL for the loadtest Vercel preview, and k6's API"
  value       = "https://${aws_cloudfront_distribution.api.domain_name}"
}

output "cluster" {
  value = aws_ecs_cluster.this.name
}

output "k6_run_task" {
  description = "Start the load: add --overrides to set PROFILE=run for the recorded run"
  value       = "aws ecs run-task --cluster ${aws_ecs_cluster.this.name} --launch-type FARGATE --task-definition ${aws_ecs_task_definition.k6.family} --network-configuration 'awsvpcConfiguration={subnets=[${join(",", local.subnets)}],securityGroups=[${aws_security_group.tasks.id}],assignPublicIp=ENABLED}'"
}

output "dashboard" {
  value = "https://${var.region}.console.aws.amazon.com/cloudwatch/home?region=${var.region}#dashboards/dashboard/${aws_cloudwatch_dashboard.this.dashboard_name}"
}

output "safety_stop_utc" {
  value = local.stop_at
}
