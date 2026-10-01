data "aws_caller_identity" "current" {}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

locals {
  aws_account_id = data.aws_caller_identity.current.account_id

  public_subnet_ids = sort(data.aws_subnets.default.ids)

  ecr_image_uri = "${aws_ecr_repository.rag_ops.repository_url}:${var.image_tag}"
}
