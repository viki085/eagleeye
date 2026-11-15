# The demo machine: Docker Compose with the services from one image, stopped by default.
# It stops itself after var.idle_minutes without requests (a systemd timer + idle check inside
# the API container; "shutdown" means stop, not terminate). No SSH: Session Manager only.

data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_instance" "demo" {
  ami                                  = data.aws_ssm_parameter.al2023.value
  instance_type                        = var.demo_instance_type
  subnet_id                            = aws_subnet.public.id
  vpc_security_group_ids               = [aws_security_group.demo.id]
  iam_instance_profile                 = aws_iam_instance_profile.demo.name
  instance_initiated_shutdown_behavior = "stop"
  user_data = templatefile("${path.module}/files/user-data.sh.tftpl", {
    region        = var.region
    account_id    = local.account_id
    ssm_env       = local.ssm_env
    ssm_root      = local.ssm_root
    deploy_bucket = aws_s3_bucket.this["deploy"].id
    idle_minutes  = var.idle_minutes
  })

  metadata_options {
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 2          # containers may use the instance role
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.demo_disk_gb
    encrypted             = true
    delete_on_termination = true
  }

  tags = { Name = "${local.name}-demo" }

  lifecycle {
    # a newer AMI must not replace the machine (and its warehouse data) on every plan
    ignore_changes = [ami]
  }
}

# A fixed public address, so CloudFront's origin survives stop/start ($0.005 an hour)
resource "aws_eip" "demo" {
  domain = "vpc"
  tags   = { Name = "${local.name}-demo" }
}

resource "aws_eip_association" "demo" {
  instance_id   = aws_instance.demo.id
  allocation_id = aws_eip.demo.id
}

# ---- the machine's permissions --------------------------------------------------------------

resource "aws_iam_role" "demo" {
  name = "${local.name}-demo-machine"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "demo_ssm_core" {
  role       = aws_iam_role.demo.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "demo" {
  name = "eagleeye-demo"
  role = aws_iam_role.demo.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadSettings"
        Effect   = "Allow"
        Action   = ["ssm:GetParametersByPath", "ssm:GetParameter"]
        Resource = "arn:${data.aws_partition.current.partition}:ssm:${var.region}:${local.account_id}:parameter${local.ssm_root}*"
      },
      {
        Sid      = "DecryptSettings"
        Effect   = "Allow"
        Action   = "kms:Decrypt"
        Resource = "*"
        Condition = {
          StringEquals = { "kms:ViaService" = "ssm.${var.region}.amazonaws.com" }
        }
      },
      {
        Sid      = "EcrLogin"
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*"
      },
      {
        Sid      = "EcrPull"
        Effect   = "Allow"
        Action   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"]
        Resource = aws_ecr_repository.this["eagleeye"].arn
      },
      {
        Sid    = "AppBuckets"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = [
          "${aws_s3_bucket.this["docs"].arn}/*",
          "${aws_s3_bucket.this["artifacts"].arn}/*",
          "${aws_s3_bucket.this["transfer"].arn}/*",
        ]
      },
      {
        Sid    = "ListAppBuckets"
        Effect = "Allow"
        Action = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = [
          aws_s3_bucket.this["docs"].arn,
          aws_s3_bucket.this["artifacts"].arn,
          aws_s3_bucket.this["transfer"].arn,
          aws_s3_bucket.this["deploy"].arn,
        ]
      },
      {
        Sid      = "ReadBundle"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.this["deploy"].arn}/bundle/*"
      },
      {
        Sid      = "RunSandbox"
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = "arn:${data.aws_partition.current.partition}:lambda:${var.region}:${local.account_id}:function:${local.sandbox_function_name}"
      },
    ]
  })
}

resource "aws_iam_instance_profile" "demo" {
  name = "${local.name}-demo-machine"
  role = aws_iam_role.demo.name
}
