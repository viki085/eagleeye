# Load balancer in front of the API tasks, behind its own CloudFront (HTTPS on *.cloudfront.net,
# nothing cached), configured like the demo's: the X-Origin-Verify secret, long reads for the
# answer streams, no compression (it would buffer the streams).

resource "aws_lb" "api" {
  name               = "${local.name}-api"
  load_balancer_type = "application"
  subnets            = local.subnets
  security_groups    = [aws_security_group.alb.id]
  idle_timeout       = 120 # answer streams stay open; they send heartbeats
}

resource "aws_lb_target_group" "api" {
  name                 = "${local.name}-api"
  port                 = 8000
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = data.aws_vpc.main.id
  deregistration_delay = 60
  health_check {
    path                = "/v1/health/live"
    matcher             = "200"
    interval            = 15
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

resource "aws_cloudfront_origin_request_policy" "api" {
  name    = "${local.name}-api"
  comment = "Load test: API headers and query strings plus CloudFront-Viewer-Address"
  cookies_config { cookie_behavior = "none" }
  query_strings_config { query_string_behavior = "all" }
  headers_config {
    header_behavior = "whitelist"
    headers {
      items = [
        "Authorization", "Content-Type", "Accept", "Origin", "Last-Event-ID", "X-Request-ID",
        "Access-Control-Request-Method", "Access-Control-Request-Headers",
        "User-Agent", "CloudFront-Viewer-Address",
      ]
    }
  }
}

resource "aws_cloudfront_distribution" "api" {
  enabled         = true
  comment         = "EagleEye API (load test)"
  price_class     = "PriceClass_100"
  is_ipv6_enabled = false
  http_version    = "http2and3"

  origin {
    origin_id   = "alb"
    domain_name = aws_lb.api.dns_name
    custom_origin_config {
      http_port                = 80
      https_port               = 443
      origin_protocol_policy   = "http-only"
      origin_ssl_protocols     = ["TLSv1.2"]
      origin_read_timeout      = 60
      origin_keepalive_timeout = 60
    }
    custom_header {
      name  = "X-Origin-Verify"
      value = random_password.origin_verify.result
    }
  }

  default_cache_behavior {
    target_origin_id         = "alb"
    viewer_protocol_policy   = "https-only"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = aws_cloudfront_origin_request_policy.api.id
    compress                 = false
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}
