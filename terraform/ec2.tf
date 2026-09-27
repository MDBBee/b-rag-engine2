data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

resource "aws_instance" "backend" {
  ami                    = data.aws_ami.amazon_linux_2023.id
  instance_type          = var.instance_type
  key_name               = var.key_name
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.backend.id]
  iam_instance_profile   = aws_iam_instance_profile.backend.name

  user_data = <<-EOF
                #!/bin/bash
                set -e

                echo "=== Installing Docker ==="
                yum update -y
                yum install -y docker
                systemctl enable docker
                systemctl start docker
                usermod -aG docker ec2-user

                echo "=== Docker installation complete ==="
                echo "Next steps:"
                echo "1. SSH in and install Caddy manually"
                echo "2. Build and push Docker image to ECR"
                echo "3. Pull image and run container"
              EOF


  root_block_device {
    volume_size = 20
    volume_type = "gp3"
  }

  tags = {
    Name = "brag-backend"
  }

  depends_on = [
    aws_internet_gateway.igw
  ]
}
