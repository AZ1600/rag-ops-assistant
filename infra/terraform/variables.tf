variable "aws_region" {
  description = "AWS region for the deployment"
  type        = string
  default     = "eu-west-2"
}

variable "aws_profile" {
  description = "Local AWS CLI profile used when running Terraform manually"
  type        = string
  default     = "one-piece-new"
}

variable "project_name" {
  description = "Project name used for AWS resource naming and tags"
  type        = string
  default     = "rag-ops-assistant"
}

variable "image_tag" {
  description = "ECR image tag deployed to ECS"
  type        = string
  default     = "v3-arm64-cpu"
}

variable "task_cpu" {
  description = "Fargate task CPU units"
  type        = number
  default     = 1024
}

variable "task_memory" {
  description = "Fargate task memory in MiB"
  type        = number
  default     = 2048
}

variable "container_port" {
  description = "Port exposed by the FastAPI container"
  type        = number
  default     = 8000
}

variable "alb_allowed_cidr" {
  description = "CIDR allowed to reach the personal-project ALB"
  type        = string
}
