variable "region" {
  description = "AWS region"
  type        = string
  default     = "eu-north-1"
}

variable "domain" {
  description = "Domain name for the backend API"
  type        = string
  default     = "yourdomain.com"
}

variable "key_name" {
  description = "EC2 key pair name"
  type        = string
  default     = "brag-key"
}

variable "your_ip" {
  description = "Your public IP address for SSH access (CIDR format, e.g., 1.2.3.4/32)"
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.micro"
}

variable "api_domain" {
  description = "API domain for backend (no protocol, e.g., api-brag.bobbyugbebor.store)"
  type        = string
}
