resource "aws_ecs_cluster" "rag_ops" {
  name = "rag-ops-assistant-cluster"
}

resource "aws_ecs_task_definition" "rag_ops" {
  family                   = "rag-ops-assistant"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]

  cpu    = tostring(var.task_cpu)
  memory = tostring(var.task_memory)

  execution_role_arn = aws_iam_role.ecs_execution.arn
  task_role_arn      = aws_iam_role.ecs_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([
    {
      name      = "rag-ops-assistant"
      image     = local.ecr_image_uri
      cpu       = 0
      essential = true

      portMappings = [
        {
          containerPort = var.container_port
          hostPort      = var.container_port
          protocol      = "tcp"
        }
      ]

      environment = []

      logConfiguration = {
        logDriver = "awslogs"

        options = {
          awslogs-group         = aws_cloudwatch_log_group.rag_ops.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "rag_ops" {
  name    = "rag-ops-assistant-service"
  cluster = aws_ecs_cluster.rag_ops.id

  task_definition = "${aws_ecs_task_definition.rag_ops.family}:${aws_ecs_task_definition.rag_ops.revision}"

  desired_count    = 1
  launch_type      = "FARGATE"
  platform_version = "LATEST"

  health_check_grace_period_seconds = 180

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets = [
      "subnet-0b196ae7fd3217cb2"
    ]

    security_groups  = [aws_security_group.task.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.rag_ops.arn
    container_name   = "rag-ops-assistant"
    container_port   = var.container_port
  }

  depends_on = [
    aws_lb_listener.http
  ]
}