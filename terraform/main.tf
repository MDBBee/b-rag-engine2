terraform {
  required_version = "~> 1.15"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  backend "s3" {
    bucket       = "brag-terraform-state-1790495705"
    key          = "b-rag-engine2/terraform.tfstate"
    region       = "eu-north-1"
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "b-rag-engine2"
      Environment = "production"
      ManagedBy   = "bobby-terraform"
    }
  }
}

data "http" "cloudflare_ips" {
  url = "https://www.cloudflare.com/ips-v4"
}

locals {
  cloudflare_ipv4 = [for ip in split("\n", data.http.cloudflare_ips.response_body) : ip if ip != ""]
}
