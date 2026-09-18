terraform {
  required_version = ">= 1.15.0, < 2.0.0"

  backend "s3" {
    bucket       = "TODO-REPLACE-TF-STATE-BUCKET"
    key          = "02_english/dev/terraform.tfstate"
    region       = "ap-northeast-1"
    encrypt      = true
    use_lockfile = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "ap-northeast-1"
}

