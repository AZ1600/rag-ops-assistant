resource "aws_lb" "rag_ops" {
  name               = "rag-ops-assistant-alb"
  internal           = false
  load_balancer_type = "application"
  ip_address_type    = "ipv4"

  security_groups = [aws_security_group.alb.id]

  subnets = [
    "subnet-098a0239a8107f00e",
    "subnet-0b196ae7fd3217cb2"
  ]
}

resource "aws_lb_target_group" "rag_ops" {
  name        = "rag-ops-assistant-tg"
  port        = var.container_port
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = data.aws_vpc.default.id

  health_check {
    enabled             = true
    protocol            = "HTTP"
    path                = "/health"
    interval            = 15
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.rag_ops.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.rag_ops.arn
  }
}
