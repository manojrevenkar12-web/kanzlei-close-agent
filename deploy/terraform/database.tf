resource "random_password" "db_admin" {
  length  = 32
  special = false
}

resource "random_password" "db_app" {
  length  = 32
  special = false
}

resource "random_password" "token_secret" {
  length  = 48
  special = false
}

resource "aws_db_subnet_group" "main" {
  name       = "${var.name}-${var.environment}"
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_parameter_group" "pg16" {
  name   = "${var.name}-${var.environment}-pg16"
  family = "postgres16"
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
  parameter {
    name  = "log_min_duration_statement"
    value = "500"
  }
}

# Row-level security in this database is what keeps one firm's clients from another's; the app
# connects as kanzlei_app (no BYPASSRLS), migrations as the master user.
resource "aws_db_instance" "main" {
  identifier                      = "${var.name}-${var.environment}"
  engine                          = "postgres"
  engine_version                  = "16"
  instance_class                  = var.db_instance_class
  allocated_storage               = 50
  max_allocated_storage           = 500
  storage_type                    = "gp3"
  storage_encrypted               = true
  db_name                         = "kanzlei"
  username                        = "kanzlei_admin"
  password                        = random_password.db_admin.result
  multi_az                        = var.db_multi_az
  db_subnet_group_name            = aws_db_subnet_group.main.name
  vpc_security_group_ids          = [aws_security_group.db.id]
  parameter_group_name            = aws_db_parameter_group.pg16.name
  backup_retention_period         = 35
  copy_tags_to_snapshot           = true
  deletion_protection             = true
  skip_final_snapshot             = false
  final_snapshot_identifier       = "${var.name}-${var.environment}-final"
  auto_minor_version_upgrade      = true
  performance_insights_enabled    = true
  enabled_cloudwatch_logs_exports = ["postgresql"]
}

locals {
  db_host = aws_db_instance.main.address
}

resource "aws_secretsmanager_secret" "app" {
  name                    = "${var.name}/${var.environment}/app"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    KANZLEI_DATABASE_URL       = "postgresql://kanzlei_app:${random_password.db_app.result}@${local.db_host}:5432/kanzlei?sslmode=require"
    KANZLEI_ADMIN_DATABASE_URL = "postgresql://kanzlei_admin:${random_password.db_admin.result}@${local.db_host}:5432/kanzlei?sslmode=require"
    KANZLEI_APP_DB_PASSWORD    = random_password.db_app.result
    KANZLEI_TOKEN_SECRET       = random_password.token_secret.result
  })
}

# Set by hand after the firm's § 62a StBerG agreement; empty keeps the model off.
resource "aws_secretsmanager_secret" "anthropic" {
  name                    = "${var.name}/${var.environment}/anthropic"
  recovery_window_in_days = 7
}
