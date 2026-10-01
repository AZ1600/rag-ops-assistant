output "ecr_repository_url" {
  value = aws_ecr_repository.rag_ops.repository_url
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.rag_ops.name
}

output "ecs_service_name" {
  value = aws_ecs_service.rag_ops.name
}

output "alb_dns_name" {
  value = aws_lb.rag_ops.dns_name
}

output "alb_url" {
  value = "http://${aws_lb.rag_ops.dns_name}"
}
