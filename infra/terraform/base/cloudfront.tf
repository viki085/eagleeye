# HTTPS in front of the API, on CloudFront's own *.cloudfront.net address (no domain needed).
# Nothing is cached (every API response is per user). CloudFront adds the secret
# X-Origin-Verify header, which the API requires, and CloudFront-Viewer-Address, from which the
# API takes the visitor's IP (the demo allowances are per IP).

data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

# CloudFront-Viewer-Address can only be added by an origin request policy that names it
resource "aws_cloudfront_origin_request_policy" "api_viewer" {
  name    = "${local.name}-api-viewer"
  comment = "API headers and query strings plus CloudFront-Viewer-Address"
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
  comment         = "EagleEye API (demo machine)"
  price_class     = "PriceClass_100" # North America and Europe edges: the cheapest class
  is_ipv6_enabled = true
  http_version    = "http2and3"

  origin {
    origin_id   = "demo"
    domain_name = aws_eip.demo.public_dns
    custom_origin_config {
      http_port                = 8000
      https_port               = 443
      origin_protocol_policy   = "http-only"
      origin_ssl_protocols     = ["TLSv1.2"]
      origin_read_timeout      = 60 # streams send a heartbeat well within this
      origin_keepalive_timeout = 60
    }
    custom_header {
      name  = "X-Origin-Verify"
      value = random_password.origin_verify.result
    }
  }

  default_cache_behavior {
    target_origin_id         = "demo"
    viewer_protocol_policy   = "https-only"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = aws_cloudfront_origin_request_policy.api_viewer.id
    compress                 = false # compression would buffer the answer streams
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
    # the *.cloudfront.net certificate only accepts this value; browsers negotiate TLS 1.2+
    minimum_protocol_version = "TLSv1"
  }
}
