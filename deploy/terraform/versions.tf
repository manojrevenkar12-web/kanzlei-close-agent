terraform {
  required_version = ">= 1.6"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.80" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
  # State in S3 with locking: terraform init -backend-config=backend.hcl
  backend "s3" {}
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      app         = "kanzlei-close-agent"
      environment = var.environment
      managed_by  = "terraform"
    }
  }
}
