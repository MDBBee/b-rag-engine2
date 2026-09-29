output "ec2_public_ip" {
  description = "Public IP address of the EC2 instance"
  value       = aws_instance.backend.public_ip
}

output "ec2_instance_id" {
  description = "Instance ID of the EC2 instance"
  value       = aws_instance.backend.id
}

output "ecr_repository_url" {
  description = "URL of the ECR repository"
  value       = aws_ecr_repository.backend.repository_url
}

output "ssh_command" {
  description = "SSH command to connect to the instance"
  value       = "ssh -i ~/.ssh/brag-key ec2-user@${aws_instance.backend.public_ip}"
}

output "vpc_id" {
  description = "ID of the VPC"
  value       = aws_vpc.main.id
}

output "cloudflare_ips" {
  description = "CURRENT CLOUDFLARE IPS"
  value       = local.cloudflare_ipv4
}

output "api_domain" {
  description = "API domain for backend"
  value       = var.api_domain
}