#!/bin/bash
set -euo pipefail

echo "=== Installing Docker ==="
yum update -y
yum install -y docker
systemctl enable docker
systemctl start docker
usermod -aG docker ec2-user

echo "=== Docker installation complete ==="

# Wait for Docker to be fully ready
sleep 5

echo "=== Setting up Docker network ==="
docker network create brag-net || echo "Network brag-net already exists"

echo "=== Creating Caddyfile ==="
cat > /home/ec2-user/Caddyfile << EOF
${api_domain} {
    reverse_proxy brag-api:8000
}
EOF
chown ec2-user:ec2-user /home/ec2-user/Caddyfile

echo "=== Logging into ECR ==="
ECR_URL="${ecr_url}"
aws ecr get-login-password --region ${region} | docker login --username AWS --password-stdin $ECR_URL

echo "=== Pulling latest image ==="
docker pull $ECR_URL:latest

echo "=== Fetching secrets from SSM ==="
export OPENROUTER_API_KEY=$(aws ssm get-parameter --name /brag/openrouter_api_key --with-decryption --query 'Parameter.Value' --output text --region ${region})
export MONGODB_URI=$(aws ssm get-parameter --name /brag/mongodb_uri --with-decryption --query 'Parameter.Value' --output text --region ${region})
export AUTH_SECRET=$(aws ssm get-parameter --name /brag/auth_secret --with-decryption --query 'Parameter.Value' --output text --region ${region})
export CORS_ORIGINS=$(aws ssm get-parameter --name /brag/cors_origins --query 'Parameter.Value' --output text --region ${region})

echo "=== Cleaning up existing containers (if any) ==="
docker stop brag-api 2>/dev/null && docker rm brag-api 2>/dev/null || echo "No existing brag-api container"
docker stop caddy 2>/dev/null && docker rm caddy 2>/dev/null || echo "No existing caddy container"

echo "=== Starting FastAPI container ==="
docker run -d \
  --name brag-api \
  --network brag-net \
  --restart unless-stopped \
  -e OPENROUTER_API_KEY="$OPENROUTER_API_KEY" \
  -e MONGODB_URI="$MONGODB_URI" \
  -e AUTH_SECRET="$AUTH_SECRET" \
  -e CORS_ORIGINS="$CORS_ORIGINS" \
  $ECR_URL:latest

echo "=== Starting Caddy container ==="
docker pull caddy:latest
docker run -d \
  --name caddy \
  --network brag-net \
  --restart unless-stopped \
  -p 80:80 \
  -p 443:443 \
  -p 443:443/udp \
  -v /home/ec2-user/Caddyfile:/etc/caddy/Caddyfile:ro \
  -v caddy_data:/data \
  -v caddy_config:/config \
  caddy:latest

echo "=== Deployment complete ==="
echo "Containers running:"
docker ps
