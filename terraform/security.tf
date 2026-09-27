resource "aws_security_group" "backend" {
  name        = "brag-backend-sg"
  description = "Security group for b-rag-engine2 backend"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTPS from Cloudflare only"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = local.cloudflare_ipv4
  }

  ingress {
    description = "HTTP from Cloudflare only (redirect to HTTPS)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = local.cloudflare_ipv4
  }

  ingress {
    description = "SSH from your IP only"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.your_ip]
  }

  egress {
    description = "All outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "brag-backend-sg"
  }
}
