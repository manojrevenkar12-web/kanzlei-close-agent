output "url" {
  value = "https://${var.domain_name}"
}

output "load_balancer_dns" {
  description = "Point domain_name here (CNAME or Route 53 alias)."
  value       = aws_lb.main.dns_name
}

output "ecr_repositories" {
  value = { for k, r in aws_ecr_repository.repo : k => r.repository_url }
}

output "documents_bucket" {
  value = aws_s3_bucket.documents.bucket
}

output "migrate_task" {
  description = "aws ecs run-task --cluster <cluster> --task-definition <this> --launch-type FARGATE ..."
  value       = aws_ecs_task_definition.migrate.arn
}

output "cluster" {
  value = aws_ecs_cluster.main.name
}

output "private_subnets" {
  value = aws_subnet.private[*].id
}

output "task_security_group" {
  value = aws_security_group.api.id
}
