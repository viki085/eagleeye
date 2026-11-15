# One VPC, no NAT gateway (about $32 a month). Two subnets:
#   public   the demo machine, with a fixed address reachable only from CloudFront
#   sandbox  the analysis function: no route to the internet at all; S3 only, through a
#            gateway endpoint whose policy allows the transfer bucket and nothing else

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "main" {
  cidr_block           = "10.40.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = local.name }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = local.name }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.40.0.0/24"
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = false # the machine gets the Elastic IP, nothing else does
  tags                    = { Name = "${local.name}-public" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
  tags = { Name = "${local.name}-public" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

resource "aws_subnet" "sandbox" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.40.10.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]
  tags              = { Name = "${local.name}-sandbox" }
}

# no default route: nothing in this subnet can reach the internet
resource "aws_route_table" "sandbox" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${local.name}-sandbox" }
}

resource "aws_route_table_association" "sandbox" {
  subnet_id      = aws_subnet.sandbox.id
  route_table_id = aws_route_table.sandbox.id
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.sandbox.id]
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "TransferBucketOnly"
      Effect    = "Allow"
      Principal = "*"
      Action    = ["s3:GetObject", "s3:PutObject"]
      Resource  = "${aws_s3_bucket.this["transfer"].arn}/*"
    }]
  })
  tags = { Name = "${local.name}-s3" }
}

# ---- security groups ------------------------------------------------------------------------

data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

resource "aws_security_group" "demo" {
  name        = "${local.name}-demo"
  description = "Demo machine: the API port from CloudFront only; no SSH (Session Manager instead)"
  vpc_id      = aws_vpc.main.id
  tags        = { Name = "${local.name}-demo" }
}

resource "aws_vpc_security_group_ingress_rule" "demo_from_cloudfront" {
  security_group_id = aws_security_group.demo.id
  description       = "API from CloudFront origin-facing addresses"
  ip_protocol       = "tcp"
  from_port         = 8000
  to_port           = 8000
  prefix_list_id    = data.aws_ec2_managed_prefix_list.cloudfront.id
}

resource "aws_vpc_security_group_egress_rule" "demo_out" {
  security_group_id = aws_security_group.demo.id
  description       = "OpenAI, Supabase, Qdrant Cloud, ECR, S3, SSM, Lambda"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_security_group" "sandbox" {
  name        = "${local.name}-sandbox"
  description = "Analysis function: no inbound; outbound HTTPS to S3 only"
  vpc_id      = aws_vpc.main.id
  tags        = { Name = "${local.name}-sandbox" }
}

resource "aws_vpc_security_group_egress_rule" "sandbox_s3" {
  security_group_id = aws_security_group.sandbox.id
  description       = "S3 through the gateway endpoint"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  prefix_list_id    = aws_vpc_endpoint.s3.prefix_list_id
}
