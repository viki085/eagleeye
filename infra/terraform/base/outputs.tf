# Nothing secret is output. The wake secret is read once from state when setting up Vercel:
#   terraform output -raw wake_secret   (marked sensitive, so plan/apply never print it)

output "api_url" {
  description = "NEXT_PUBLIC_API_URL for the web app"
  value       = "https://${aws_cloudfront_distribution.api.domain_name}"
}

output "wake_url" {
  description = "WAKE_URL for the web app"
  value       = aws_lambda_function_url.wake.function_url
}

output "wake_secret" {
  description = "WAKE_SECRET for the web app"
  value       = random_password.wake.result
  sensitive   = true
}

output "demo_instance_id" {
  value = aws_instance.demo.id
}

output "ecr_repositories" {
  value = { for k, r in aws_ecr_repository.this : k => r.repository_url }
}

output "deploy_role_arn" {
  description = "AWS_DEPLOY_ROLE_ARN for the GitHub deploy workflow"
  value       = aws_iam_role.deploy.arn
}

output "buckets" {
  value = { for k, b in aws_s3_bucket.this : k => b.id }
}
