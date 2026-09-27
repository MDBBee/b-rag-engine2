resource "aws_ssm_parameter" "openrouter_api_key" {
  name  = "/brag/openrouter_api_key"
  type  = "SecureString"
  value = "REPLACE_WITH_YOUR_KEY"

  lifecycle {
    ignore_changes = [value]
  }

  tags = {
    Name = "openrouter_api_key"
  }
}

resource "aws_ssm_parameter" "mongodb_uri" {
  name  = "/brag/mongodb_uri"
  type  = "SecureString"
  value = "REPLACE_WITH_YOUR_URI"

  lifecycle {
    ignore_changes = [value]
  }

  tags = {
    Name = "mongodb_uri"
  }
}

resource "aws_ssm_parameter" "auth_secret" {
  name  = "/brag/auth_secret"
  type  = "SecureString"
  value = "REPLACE_WITH_YOUR_SECRET"

  lifecycle {
    ignore_changes = [value]
  }

  tags = {
    Name = "auth_secret"
  }
}

resource "aws_ssm_parameter" "cors_origins" {
  name  = "/brag/cors_origins"
  type  = "String"
  value = "https://${var.domain}"

  tags = {
    Name = "cors_origins"
  }
}
