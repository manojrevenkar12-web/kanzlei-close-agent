locals {
  prefix  = "${var.name}-${var.environment}"
  ecr     = { for k, r in aws_ecr_repository.repo : k => "${r.repository_url}:${var.image_tag}" }
  secrets = aws_secretsmanager_secret.app.arn
  app_env = [
    { name = "KANZLEI_STORAGE_URL", value = "s3://${aws_s3_bucket.documents.bucket}/documents" },
    { name = "KANZLEI_PUBLIC_URL", value = "https://${var.domain_name}" },
    { name = "KANZLEI_CORS_ORIGIN", value = "https://${var.domain_name}" },
    { name = "KANZLEI_DEMO_MODE", value = tostring(var.demo_mode) },
    { name = "KANZLEI_ALB_ARN", value = var.oidc == null ? "" : aws_lb.main.arn },
    { name = "KANZLEI_AWS_REGION", value = var.region },
    { name = "KANZLEI_SMTP_HOST", value = var.smtp_host },
  ]
  app_secrets = concat(
    [for k in ["KANZLEI_DATABASE_URL", "KANZLEI_ADMIN_DATABASE_URL", "KANZLEI_APP_DB_PASSWORD", "KANZLEI_TOKEN_SECRET"] :
    { name = k, valueFrom = "${local.secrets}:${k}::" }],
    var.llm_enabled ? [{ name = "ANTHROPIC_API_KEY", valueFrom = aws_secretsmanager_secret.anthropic.arn }] : [],
  )
  log = { for k in ["api", "worker", "web", "migrate"] : k => {
    logDriver = "awslogs"
    options = {
      awslogs-group         = aws_cloudwatch_log_group.app.name
      awslogs-region        = var.region
      awslogs-stream-prefix = k
    }
  } }
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${local.prefix}"
  retention_in_days = 90
}

resource "aws_ecs_cluster" "main" {
  name = local.prefix
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_service_discovery_http_namespace" "main" {
  name = local.prefix
}

# --- roles -----------------------------------------------------------------------------------------

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${local.prefix}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "execution_secrets" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.app.arn, aws_secretsmanager_secret.anthropic.arn]
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secrets.json
}

# The app may write new objects and read them; it can never delete one (Object Lock would refuse
# anyway) and it cannot change retention.
data "aws_iam_policy_document" "app" {
  statement {
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${aws_s3_bucket.documents.arn}/documents/*"]
  }
  statement {
    actions   = ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.documents.arn]
  }
}

resource "aws_iam_role" "app" {
  name               = "${local.prefix}-app"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "app" {
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.app.json
}

# --- task definitions ------------------------------------------------------------------------------

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.prefix}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 2048
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.app.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
  container_definitions = jsonencode([{
    name                   = "api"
    image                  = local.ecr["api"]
    essential              = true
    readonlyRootFilesystem = true
    portMappings           = [{ name = "http", containerPort = 8000, protocol = "tcp", appProtocol = "http" }]
    environment            = local.app_env
    secrets                = local.app_secrets
    mountPoints            = [{ sourceVolume = "tmp", containerPath = "/tmp" }]
    logConfiguration       = local.log["api"]
    healthCheck = {
      command  = ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"]
      interval = 15
      timeout  = 5
      retries  = 3
    }
  }])
  volume {
    name = "tmp"
  }
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.prefix}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.app.arn
  container_definitions = jsonencode([{
    name             = "worker"
    image            = local.ecr["api"]
    essential        = true
    command          = ["kanzlei", "worker"]
    environment      = local.app_env
    secrets          = local.app_secrets
    logConfiguration = local.log["worker"]
  }])
}

# One-off: CI runs it with `aws ecs run-task` before rolling out a new image.
resource "aws_ecs_task_definition" "migrate" {
  family                   = "${local.prefix}-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.app.arn
  container_definitions = jsonencode([{
    name             = "migrate"
    image            = local.ecr["api"]
    essential        = true
    command          = ["kanzlei", "migrate"]
    environment      = local.app_env
    secrets          = local.app_secrets
    logConfiguration = local.log["migrate"]
  }])
}

resource "aws_ecs_task_definition" "web" {
  family                   = "${local.prefix}-web"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  container_definitions = jsonencode([{
    name             = "web"
    image            = local.ecr["web"]
    essential        = true
    portMappings     = [{ name = "web", containerPort = 8080, protocol = "tcp" }]
    environment      = [{ name = "API_UPSTREAM", value = "http://api:8000" }]
    logConfiguration = local.log["web"]
  }])
}

# --- services --------------------------------------------------------------------------------------

resource "aws_ecs_service" "api" {
  name                   = "api"
  cluster                = aws_ecs_cluster.main.id
  task_definition        = aws_ecs_task_definition.api.arn
  desired_count          = var.api_desired_count
  launch_type            = "FARGATE"
  enable_execute_command = false
  network_configuration {
    subnets         = aws_subnet.private[*].id
    security_groups = [aws_security_group.api.id]
  }
  service_connect_configuration {
    enabled   = true
    namespace = aws_service_discovery_http_namespace.main.arn
    service {
      port_name = "http"
      client_alias {
        dns_name = "api"
        port     = 8000
      }
    }
  }
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
}

resource "aws_ecs_service" "worker" {
  name            = "worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = 1
  launch_type     = "FARGATE"
  network_configuration {
    subnets         = aws_subnet.private[*].id
    security_groups = [aws_security_group.api.id]
  }
}

resource "aws_ecs_service" "web" {
  name            = "web"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.web.arn
  desired_count   = 2
  launch_type     = "FARGATE"
  network_configuration {
    subnets         = aws_subnet.private[*].id
    security_groups = [aws_security_group.web.id]
  }
  service_connect_configuration {
    enabled   = true
    namespace = aws_service_discovery_http_namespace.main.arn
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.web.arn
    container_name   = "web"
    container_port   = 8080
  }
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  depends_on = [aws_lb_listener.https]
}

# --- load balancer ---------------------------------------------------------------------------------

resource "aws_lb" "main" {
  name                       = local.prefix
  load_balancer_type         = "application"
  subnets                    = aws_subnet.public[*].id
  security_groups            = [aws_security_group.alb.id]
  drop_invalid_header_fields = true
  enable_deletion_protection = true
}

resource "aws_lb_target_group" "web" {
  name        = "${local.prefix}-web"
  port        = 8080
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id
  health_check {
    path    = "/api/health"
    matcher = "200"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# Staff pages sit behind the group's identity provider; the API checks the load balancer's signed
# header (src/kanzlei/api/alb_oidc.py) and still reads rights from the database.
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  dynamic "default_action" {
    for_each = var.oidc == null ? [] : [var.oidc]
    content {
      type  = "authenticate-oidc"
      order = 1
      authenticate_oidc {
        issuer                     = default_action.value.issuer
        authorization_endpoint     = default_action.value.authorization_endpoint
        token_endpoint             = default_action.value.token_endpoint
        user_info_endpoint         = default_action.value.user_info_endpoint
        client_id                  = default_action.value.client_id
        client_secret              = default_action.value.client_secret
        scope                      = "openid email profile"
        session_timeout            = 28800
        on_unauthenticated_request = "authenticate"
      }
    }
  }

  default_action {
    type             = "forward"
    order            = 2
    target_group_arn = aws_lb_target_group.web.arn
  }
}

# Clients answer questions through a link without an account: the portal, its API and the static
# files skip the identity provider. The token in the link is the only key, stored hashed.
resource "aws_lb_listener_rule" "public" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 10
  condition {
    path_pattern {
      values = ["/portal/*", "/api/portal/*", "/assets/*", "/api/health", "/favicon.svg"]
    }
  }
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}
