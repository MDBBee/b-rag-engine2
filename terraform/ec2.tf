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

  user_data = templatefile("${path.module}/user-data.sh", {
    region     = var.region
    api_domain = var.api_domain
    ecr_url    = aws_ecr_repository.backend.repository_url
  })

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
  }

  tags = {
    Name = "brag-backend"
  }

  depends_on = [
    aws_internet_gateway.igw,
    aws_ecr_repository.backend
  ]
}
