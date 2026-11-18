# The ECS cluster, its services and their settings. The app image runs api / gateway /
# agent-worker / ingest-worker (chosen by SERVICE), with the same settings shape as the demo
# machine but APP_ENV=loadtest and the stand-in model (no OpenAI calls, no cost).

resource "aws_ecs_cluster" "this" {
  name = local.name
  setting {
    name  = "containerInsights"
    value = "enabled" # running-task counts per service, for the dashboard and the video
  }
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/eagleeye/loadtest"
  retention_in_days = 7
}

# load-test documents and artifacts (emptied and removed by destroy)
resource "aws_s3_bucket" "files" {
  bucket        = "${local.name}-files-${local.account}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "files" {
  bucket                  = aws_s3_bucket.files.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "random_password" "db" {
  length  = 32
  special = false
}

resource "random_password" "gateway_hmac" {
  length  = 48
  special = false
}

resource "random_password" "origin_verify" {
  length  = 48
  special = false
}

resource "aws_ssm_parameter" "secret" {
  for_each = {
    DATABASE_URL              = "postgresql://postgres:${random_password.db.result}@appdb.${local.ns}:5432/postgres"
    POSTGRES_PASSWORD         = random_password.db.result
    GATEWAY_HMAC_SECRET       = random_password.gateway_hmac.result
    ORIGIN_VERIFY_SECRET      = random_password.origin_verify.result
    LOADTEST_TOKEN_PUBLIC_KEY = file(var.loadtest_public_key_file)
  }
  name  = "/eagleeye/loadtest/${each.key}"
  type  = "SecureString"
  value = each.value
}

locals {
  # settings every app service gets (not secret)
  app_env = {
    APP_ENV                 = "loadtest"
    LLM_PROVIDER            = "stub"
    LOG_FORMAT              = "json"
    AWS_REGION              = var.region
    WEB_ORIGIN              = var.web_origin
    REDIS_URL               = "redis://redis.${local.ns}:6379/0"
    QDRANT_URL              = "http://qdrant.${local.ns}:6333"
    GATEWAY_URL             = "http://gateway.${local.ns}:8100"
    WAREHOUSE_DSN           = "postgresql://eagleeye_ro:eagleeye-ro-local@warehouse.${local.ns}:5432/warehouse"
    S3_ENDPOINT_URL         = "" # empty endpoint and keys: boto3 uses the task's role
    S3_ACCESS_KEY           = ""
    S3_SECRET_KEY           = ""
    DOCS_BUCKET             = aws_s3_bucket.files.id
    ARTIFACTS_BUCKET        = aws_s3_bucket.files.id
    SANDBOX_TRANSFER_BUCKET = local.buckets["transfer"] # the sandbox's network only reaches this bucket
    SANDBOX_BACKEND         = "lambda"
    SANDBOX_LAMBDA_FUNCTION = "eagleeye-sandbox"
    SANDBOX_TIMEOUT_S       = "60"
    QUEUE_METRIC_ENABLED    = "true"
    METRIC_NAMESPACE        = "EagleEye/LoadTest"
    FIGURES_ENABLED         = "false" # no vision model in the load test
    # our own database (not Supabase's small pooler): larger pools per process
    DB_POOL_MAX_API     = "20"
    DB_POOL_MAX_WORKER  = "10"
    DB_POOL_MAX_GATEWAY = "8"
    # every simulated user arrives from the k6 task's one address: the per-user limits stay,
    # the per-address limit is lifted for the test
    RATE_LIMIT_IP_PER_MIN = "1000000"
    FORWARDED_ALLOW_IPS   = "*"
    AGENT_CONCURRENCY     = "8"
  }
  app_secrets = ["DATABASE_URL", "GATEWAY_HMAC_SECRET", "ORIGIN_VERIFY_SECRET", "LOADTEST_TOKEN_PUBLIC_KEY"]
  clerk_secrets = {
    CLERK_SECRET_KEY                  = "/eagleeye/demo/env/CLERK_SECRET_KEY"
    NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY = "/eagleeye/demo/env/NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY"
  }

  services = {
    api           = { image = local.app_image, cpu = 512, memory = 1024, port = 8000, app = true, desired = 1 }
    agent-worker  = { image = local.app_image, cpu = 1024, memory = 2048, port = 0, app = true, desired = 1 }
    ingest-worker = { image = local.app_image, cpu = 2048, memory = 4096, port = 0, app = true, desired = 1 }
    gateway       = { image = local.app_image, cpu = 512, memory = 1024, port = 8100, app = true, desired = 1 }
    redis         = { image = "public.ecr.aws/docker/library/redis:7-alpine", cpu = 1024, memory = 2048, port = 6379, app = false, desired = 1 }
    qdrant        = { image = "qdrant/qdrant:v1.13.4", cpu = 1024, memory = 2048, port = 6333, app = false, desired = 1 }
    appdb         = { image = "${local.ecr}:${var.appdb_image_tag}", cpu = 2048, memory = 4096, port = 5432, app = false, desired = 1 }
    warehouse     = { image = "${local.ecr}:${var.warehouse_image_tag}", cpu = 1024, memory = 2048, port = 5432, app = false, desired = 1 }
  }
}

# --- roles -----------------------------------------------------------------------------------

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${local.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_ssm" {
  name = "read-settings"
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ssm:GetParameters"]
      Resource = concat([for p in aws_ssm_parameter.secret : p.arn], [for _, n in local.clerk_secrets : "arn:aws:ssm:${var.region}:${local.account}:parameter${n}"])
    }]
  })
}

resource "aws_iam_role" "task" {
  name               = "${local.name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "task" {
  name = "app"
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
        Resource = [aws_s3_bucket.files.arn, "${aws_s3_bucket.files.arn}/*", "arn:aws:s3:::${local.buckets["transfer"]}", "arn:aws:s3:::${local.buckets["transfer"]}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = "arn:aws:lambda:${var.region}:${local.account}:function:eagleeye-sandbox"
      },
      {
        Effect    = "Allow"
        Action    = ["cloudwatch:PutMetricData"]
        Resource  = "*"
        Condition = { StringEquals = { "cloudwatch:namespace" = "EagleEye/LoadTest" } }
      },
    ]
  })
}

# --- task definitions and services --------------------------------------------------------

resource "aws_ecs_task_definition" "svc" {
  for_each                 = local.services
  family                   = "${local.name}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = each.value.cpu
  memory                   = each.value.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
  container_definitions = jsonencode([{
    name         = each.key
    image        = each.value.image
    essential    = true
    stopTimeout  = each.value.app ? 120 : 30 # answers in progress get time to finish
    portMappings = each.value.port > 0 ? [{ containerPort = each.value.port, protocol = "tcp" }] : []
    environment = each.value.app ? [for k, v in merge(local.app_env, { SERVICE = each.key }) : { name = k, value = v }] : (
      each.key == "appdb" ? [{ name = "POSTGRES_DB", value = "postgres" }] : (
        each.key == "warehouse" ? [{ name = "POSTGRES_DB", value = "warehouse" }, { name = "POSTGRES_USER", value = "warehouse_admin" }] : []
      )
    )
    secrets = each.value.app ? concat(
      [for k in local.app_secrets : { name = k, valueFrom = aws_ssm_parameter.secret[k].arn }],
      [for k, n in local.clerk_secrets : { name = k, valueFrom = "arn:aws:ssm:${var.region}:${local.account}:parameter${n}" }],
    ) : (contains(["appdb", "warehouse"], each.key) ? [{ name = "POSTGRES_PASSWORD", valueFrom = aws_ssm_parameter.secret["POSTGRES_PASSWORD"].arn }] : [])
    command = each.key == "redis" ? ["redis-server", "--save", "", "--appendonly", "no"] : null
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.this.name
        awslogs-region        = var.region
        awslogs-stream-prefix = each.key
        mode                  = "non-blocking"
      }
    }
  }])
}

resource "aws_service_discovery_service" "svc" {
  for_each = { for k, v in local.services : k => v if v.port > 0 }
  name     = each.key
  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.this.id
    routing_policy = "MULTIVALUE"
    dns_records {
      type = "A"
      ttl  = 10
    }
  }
}

resource "aws_ecs_service" "svc" {
  for_each               = local.services
  name                   = each.key
  cluster                = aws_ecs_cluster.this.id
  task_definition        = aws_ecs_task_definition.svc[each.key].arn
  desired_count          = each.value.desired
  launch_type            = "FARGATE"
  enable_execute_command = false
  # start the data services first; the app services retry their connections anyway
  health_check_grace_period_seconds = each.key == "api" ? 120 : null
  network_configuration {
    subnets          = local.subnets
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = true # image pulls without a NAT gateway
  }
  dynamic "service_registries" {
    for_each = each.value.port > 0 ? [1] : []
    content {
      registry_arn = aws_service_discovery_service.svc[each.key].arn
    }
  }
  dynamic "load_balancer" {
    for_each = each.key == "api" ? [1] : []
    content {
      target_group_arn = aws_lb_target_group.api.arn
      container_name   = "api"
      container_port   = 8000
    }
  }
  lifecycle {
    ignore_changes = [desired_count] # autoscaling owns it
  }
  depends_on = [aws_lb_listener.http]
}

# --- k6 (run on demand: aws ecs run-task ...) --------------------------------------------

resource "aws_ecs_task_definition" "k6" {
  family                   = "${local.name}-k6"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 4096
  memory                   = 8192
  execution_role_arn       = aws_iam_role.execution.arn
  container_definitions = jsonencode([{
    name      = "k6"
    image     = "${local.ecr}:${var.k6_image_tag}"
    essential = true
    environment = [
      { name = "API", value = "https://${aws_cloudfront_distribution.api.domain_name}" },
      { name = "PROFILE", value = "rehearsal" },
      { name = "K6_NO_USAGE_REPORT", value = "true" },
    ]
    ulimits = [{ name = "nofile", softLimit = 65536, hardLimit = 65536 }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.this.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "k6"
      }
    }
  }])
}
