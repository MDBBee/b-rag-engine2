# Deployment Guide — b-rag-engine2

**Reproducible step-by-step instructions for deploying the FastAPI backend to AWS.**

---

## Table of Contents

- [1. Architecture Overview](#1-architecture-overview)
- [2. Prerequisites](#2-prerequisites)
- [3. Phase 0: One-Time Setup](#3-phase-0-one-time-setup)
- [4. Phase 1: Terraform Infrastructure](#4-phase-1-terraform-infrastructure)
- [5. Phase 2: SSM Secrets](#5-phase-2-ssm-secrets)
- [6. Phase 3: DNS Configuration](#6-phase-3-dns-configuration)
- [7. Phase 4: Docker Build & Push](#7-phase-4-docker-build--push)
- [8. Phase 5: Deploy Containers](#8-phase-5-deploy-containers)
- [9. Phase 6: Verify Deployment](#9-phase-6-verify-deployment)
- [10. Phase 7: Ongoing Redeploy](#10-phase-7-ongoing-redeploy)
- [11. GitHub Actions CI/CD Setup](#11-github-actions-cicd-setup)
- [12. Docker Optimization](#12-docker-optimization)
- [13. Troubleshooting](#13-troubleshooting)
- [14. Cost Summary](#14-cost-summary)
- [15. Quick Reference Commands](#15-quick-reference-commands)

---

## 1. Architecture Overview

### High-Level Diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│                                                                          │
│   User Browser                                                           │
│       │                                                                  │
│       ├──▶ brag.bobbyugbebor.store ──▶ Vercel (Next.js frontend)        │
│       │                                                                  │
│       └──▶ api-brag.bobbyugbebor.store ──▶ Cloudflare (DNS + WAF)       │
│                                              │                           │
└──────────────────────────────────────────────┼───────────────────────────┘
                                               │
┌──────────────────────────────────────────────┼───────────────────────────┐
│                          AWS (eu-north-1)    │                           │
│                                              ▼                           │
│  ┌─── VPC (10.0.0.0/16) ───────────────────────────────────────────┐   │
│  │                                                                  │   │
│  │  ┌─── Public Subnet (10.0.1.0/24) ───────────────────────────┐  │   │
│  │  │                                                            │  │   │
│  │  │   ┌────────────────────────────────────────────────────┐   │  │   │
│  │  │   │         t3.micro EC2 Instance (Amazon Linux 2023)  │   │  │   │
│  │  │   │         Public IP: <EC2_IP>                        │   │  │   │
│  │  │   │                                                    │   │  │   │
│  │  │   │   ┌──────────────────┐    ┌────────────────────┐   │   │  │   │
│  │  │   │   │  Caddy Container │───▶│  FastAPI Container │   │   │  │   │
│  │  │   │   │  :80 / :443      │    │  :8000 (internal)  │   │   │  │   │
│  │  │   │   │  (Docker, auto   │    │                    │   │   │  │   │
│  │  │   │   │   Let's Encrypt) │    │  Not exposed to    │   │   │  │   │
│  │  │   │   │                  │    │  internet directly │   │   │  │   │
│  │  │   │   └──────────────────┘    └────────────────────┘   │   │  │   │
│  │  │   │         ▲                                          │   │  │   │
│  │  │   │         │ Docker network: brag-net                  │   │  │   │
│  │  │   └─────────┼──────────────────────────────────────────┘   │  │   │
│  │  │             │                                               │  │   │
│  │  └─────────────┼───────────────────────────────────────────────┘  │   │
│  │                │                                                   │   │
│  │           Internet Gateway                                         │   │
│  └────────────────┼───────────────────────────────────────────────────┘   │
│                   │                                                        │
│  ┌────────────────┼───────┐   ┌────────────────────────────────────────┐  │
│  │  ECR           │       │   │  SSM Parameter Store                   │  │
│  │  b-rag-engine2 │◀─pull─│   │  /brag/openrouter_api_key (Secure)    │  │
│  │  (Docker image)│       │   │  /brag/mongodb_uri        (Secure)    │  │
│  └────────────────────────┘   │  /brag/auth_secret        (Secure)    │  │
│                               │  /brag/cors_origins       (String)    │  │
│                               └────────────────────────────────────────┘  │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  S3 Bucket: brag-terraform-state-1790495705 (state + locking)   │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
```

### Network Traffic Flow (Security Layers)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              INTERNET                                            │
│                                                                                 │
│   User Browser                                                                  │
│        │                                                                        │
│        │ 1. DNS Query: api-brag.bobbyugbebor.store                              │
│        ▼                                                                        │
│   ┌─────────────────┐                                                           │
│   │   Cloudflare    │  ◄── DNS + WAF + DDoS Protection                          │
│   │   Edge Network  │      (Proxied DNS - Orange Cloud)                         │
│   └────────┬────────┘                                                           │
│            │ 2. Cloudflare forwards request                                     │
│            │    Source IP: Cloudflare IP (not user IP)                           │
│            ▼                                                                    │
└────────────┼────────────────────────────────────────────────────────────────────┘
             │
┌────────────┼────────────────────────────────────────────────────────────────────┐
│            │         AWS VPC (eu-north-1)                                        │
│            ▼                                                                     │
│   ┌────────────────────────────────────────────────────────────────────────┐    │
│   │  EC2 Security Group: brag-backend-sg                                   │    │
│   │  ┌─────────────────────────────────────────────────────────────────┐   │    │
│   │  │  Port 443 (HTTPS): Cloudflare IPs ONLY  ✓ ALLOWED               │   │    │
│   │  │  Port 80  (HTTP):  Cloudflare IPs ONLY  ✓ ALLOWED               │   │    │
│   │  │  Port 22  (SSH):   Your IP ONLY         ✓ ALLOWED               │   │    │
│   │  │  All other traffic:                     ✗ BLOCKED                │   │    │
│   │  └─────────────────────────────────────────────────────────────────┘   │    │
│   │                                                                        │    │
│   │  Direct access to EC2 IP from non-Cloudflare IPs: BLOCKED              │    │
│   └────────────────────────────────────────────────────────────────────────┘    │
│            │                                                                     │
│            ▼                                                                     │
│   ┌────────────────────────────────────────────────────────────────────────┐    │
│   │  EC2 Instance: t3.micro (Amazon Linux 2023)                            │    │
│   │                                                                        │    │
│   │  ┌──────────────────────────────────────────────────────────────────┐ │    │
│   │  │  Docker Network: brag-net (isolated)                             │ │    │
│   │  │                                                                  │ │    │
│   │  │  ┌─────────────────┐         ┌─────────────────────────────┐    │ │    │
│   │  │  │ Caddy Container │────────▶│ FastAPI Container           │    │ │    │
│   │  │  │ :80, :443       │         │ :8000 (internal only)       │    │ │    │
│   │  │  │ (public facing) │         │ (not exposed to internet)   │    │ │    │
│   │  │  └─────────────────┘         └─────────────────────────────┘    │ │    │
│   │  │                                                                  │ │    │
│   │  └──────────────────────────────────────────────────────────────────┘ │    │
│   └────────────────────────────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────────────────────────┘
```

### Security Group Rules

| Port | Protocol | Source                 | Purpose                    | Status       |
| ---- | -------- | ---------------------- | -------------------------- | ------------ |
| 443  | TCP      | Cloudflare IPv4 ranges | HTTPS from Cloudflare only | ✓ Restricted |
| 80   | TCP      | Cloudflare IPv4 ranges | HTTP redirect to HTTPS     | ✓ Restricted |
| 22   | TCP      | `your_ip/32`           | SSH access (your IP only)  | ✓ Restricted |
| All  | All      | 0.0.0.0/0              | Outbound (egress)          | ✓ Allowed    |

**Cloudflare IP ranges are fetched dynamically from `https://www.cloudflare.com/ips-v4` during `terraform plan/apply`.**

### Key Design Decisions

| Decision                                | Rationale                                                                                                      |
| --------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| **Docker Caddy** (not system-installed) | Always latest version, avoids COPR compatibility issues with Amazon Linux 2023, auto-updates with `docker pull` |
| **Docker network** (`brag-net`)         | FastAPI container is internal-only — not exposed to internet. Only Caddy talks to it                           |
| **Cloudflare as primary DNS**           | Single DNS provider for both frontend (Vercel) and backend (EC2)                                               |
| **SSM Parameter Store**                 | Secrets encrypted at rest, fetched at runtime — never baked into Docker image                                  |
| **Manual deployment**                   | Full control, easier to debug, no deploy.sh abstraction                                                        |

---

## 2. Prerequisites

- [Terraform](https://developer.hashicorp.com/terraform/install) ~> 1.15
- [AWS CLI](https://aws.amazon.com/cli/) configured with your credentials
- [Docker](https://docs.docker.com/get-docker/) installed locally
- A domain on Namecheap (or any registrar)
- A free [Cloudflare](https://dash.cloudflare.com/) account
- A [Vercel](https://vercel.com/) account (frontend hosting)

---

## 3. Phase 0: One-Time Setup

**What it does:** Creates the S3 bucket for Terraform state (with native S3 locking) and SSH key pair.

### 0a. S3 Backend Bucket

```bash
# Create S3 bucket for Terraform state (copy the bucket name from output)
aws s3api create-bucket \
  --bucket brag-terraform-state-$(date +%s) \
  --region eu-north-1 \
  --create-bucket-configuration LocationConstraint=eu-north-1

# Enable versioning (replace <BUCKET_NAME> with the name from above)
aws s3api put-bucket-versioning \
  --bucket <BUCKET_NAME> \
  --versioning-configuration Status=Enabled
```

**Example output:**
```json
{
  "Location": "http://brag-terraform-state-1790495705.s3.amazonaws.com/"
}
```

> **Note:** Copy just the bucket name (e.g., `brag-terraform-state-1790495705`) — not the full URL.

### 0b. SSH Key Pair

```bash
# Generate SSH key (ed25519 is modern, secure, short)
ssh-keygen -t ed25519 -C "brag-ec2" -f ~/.ssh/brag-key -N ""

# This creates:
# ~/.ssh/brag-key       (private key, keep secret)
# ~/.ssh/brag-key.pub   (public key, upload to AWS)
```

### 0c. Upload Public Key to AWS

```bash
# Import the public key as an EC2 key pair
aws ec2 import-key-pair \
  --key-name brag-key \
  --public-key-material fileb://~/.ssh/brag-key.pub \
  --region eu-north-1
```

**Verify:**
```bash
aws ec2 describe-key-pairs --key-names brag-key --region eu-north-1
```

### 0d. Update main.tf with Your Bucket Name

Edit `terraform/main.tf` and replace the bucket name:

```hcl
terraform {
  required_version = "~> 1.15"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  backend "s3" {
    bucket         = "brag-terraform-state-XXXXXXXXXX"  # ← Your bucket name here
    key            = "b-rag-engine2/terraform.tfstate"
    region         = "eu-north-1"
    use_lockfile   = true
    encrypt        = true
  }
}
```

### 0e. Configure Variables

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
```

**Edit `terraform.tfvars`:**
```hcl
region        = "eu-north-1"
domain        = "bobbyugbebor.store"
key_name      = "brag-key"
your_ip       = "37.33.148.179/32"   # ← Your public IP (run: curl ifconfig.me)
instance_type = "t3.micro"
```

**Get your public IP:**
```bash
curl ifconfig.me
```

Then add `/32` to the end (e.g., `37.33.148.179/32`). This restricts SSH access to your IP only.

---

## 4. Phase 1: Terraform Infrastructure

**What it does:** Creates VPC, subnet, security group, IAM role, ECR repo, SSM parameters, and EC2 instance with Docker pre-installed.

**Files:**
```
terraform/
├── main.tf              # Provider (~> 6.0) + S3 backend
├── variables.tf         # Inputs: region, domain, key_name, your_ip
├── outputs.tf           # EC2 public IP, ECR URL, SSH command
├── vpc.tf               # VPC + public subnet + IGW + route table
├── security.tf          # SG: 443, 80 (Cloudflare), 22 (your IP only)
├── ecr.tf               # ECR repository + lifecycle policy (keep last 5)
├── iam.tf               # EC2 role + separate policy resources (modern syntax)
├── ssm.tf               # SecureString parameters (placeholders, you fill)
├── ec2.tf               # t3.micro + Docker user-data
└── terraform.tfvars     # Your actual values
```

### 1a. Initialize and Apply

```bash
cd terraform
terraform init -upgrade
terraform plan
terraform apply
```

> **Note:** If SSM parameters already exist from a previous run, import them:
>
> ```bash
> terraform import aws_ssm_parameter.openrouter_api_key /brag/openrouter_api_key
> terraform import aws_ssm_parameter.mongodb_uri /brag/mongodb_uri
> terraform import aws_ssm_parameter.auth_secret /brag/auth_secret
> terraform import aws_ssm_parameter.cors_origins /brag/cors_origins
> ```

**What you get:**
- EC2 instance with Docker installed (user-data only installs Docker)
- ECR repository ready for your image
- SSM parameters created with placeholder values
- Security group: 80/443 restricted to Cloudflare IPs, 22 restricted to your IP

**Outputs:**
```bash
terraform output ec2_public_ip       # EC2 public IP
terraform output ssh_command         # SSH command
terraform output ecr_repository_url  # ECR URL for Docker push
```

---

## 5. Phase 2: SSM Secrets

**What it does:** Stores your API keys securely in SSM Parameter Store (encrypted at rest with AWS-managed KMS key).

**Important:** SSM parameters are managed manually, not in Terraform. This prevents accidental resets when Terraform recreates resources.

**Parameters to set:**

| Parameter                  | Type         | Description                             |
| -------------------------- | ------------ | --------------------------------------- |
| `/brag/openrouter_api_key` | SecureString | Your OpenRouter API key                 |
| `/brag/mongodb_uri`        | SecureString | MongoDB Atlas connection string         |
| `/brag/auth_secret`        | SecureString | Shared JWT secret (must match frontend) |
| `/brag/cors_origins`       | String       | Comma-separated frontend origins        |

**Commands:**
```bash
# OpenRouter API Key
aws ssm put-parameter \
  --name "/brag/openrouter_api_key" \
  --value "sk-or-v1-..." \
  --type SecureString \
  --region eu-north-1

# MongoDB URI
aws ssm put-parameter \
  --name "/brag/mongodb_uri" \
  --value "mongodb+srv://user:pass@cluster.mongodb.net/?retryWrites=true&w=majority" \
  --type SecureString \
  --region eu-north-1

# Auth Secret (must match frontend AUTH_SECRET)
aws ssm put-parameter \
  --name "/brag/auth_secret" \
  --value "your-jwt-secret-here" \
  --type SecureString \
  --region eu-north-1

# CORS Origins
aws ssm put-parameter \
  --name "/brag/cors_origins" \
  --value "http://localhost:3000,https://brag.bobbyugbebor.store,https://b-rag-view.vercel.app" \
  --type String \
  --region eu-north-1
```

> **Note:** Run these commands once. If you need to update a parameter later, add `--overwrite` to the command.

**Verify:**
```bash
aws ssm get-parameters-by-path \
  --path /brag \
  --with-decryption \
  --region eu-north-1
```

---

## 6. Phase 3: DNS Configuration

**What it does:** Sets up Cloudflare as the primary DNS provider, pointing the frontend to Vercel and the backend to EC2.

### 3a. Add Domain to Cloudflare

1. Go to [Cloudflare Dashboard](https://dash.cloudflare.com/)
2. Click **Add a site**
3. Enter `bobbyugbebor.store`
4. Select **Free plan**
5. Cloudflare scans existing DNS records
6. Click **Continue**
7. Cloudflare gives you two nameservers (e.g., `aria.ns.cloudflare.com`, `bob.ns.cloudflare.com`)
8. **Keep this tab open**

### 3b. Update Namecheap Nameservers

1. Go to [Namecheap Dashboard](https://ap.www.namecheap.com/)
2. Click **Domain List** → `bobbyugbebor.store` → **Nameservers**
3. Select **Custom DNS** from dropdown
4. Enter the two Cloudflare nameservers
5. Click green checkmark to save
6. **Wait 5-30 minutes** for propagation (can take up to 24h)

**Verify propagation:**
```bash
dig bobbyugbebor.store NS +short
```

### 3c. Add DNS Records in Cloudflare

1. In Cloudflare dashboard, go to **DNS** → **Records**
2. Click **Add record**

**Add these records:**

| Type  | Name       | Content                 | Proxy status           | Purpose            |
| ----- | ---------- | ----------------------- | ---------------------- | ------------------ |
| CNAME | `brag`     | `b-rag-view.vercel.app` | DNS only (gray cloud)  | Frontend on Vercel |
| A     | `api-brag` | `<EC2_PUBLIC_IP>`       | Proxied (orange cloud) | Backend on EC2     |

> **Important:**
> - CNAME target must be hostname only — **no** `https://`, **no** trailing `/`
> - Frontend CNAME must be **DNS only** (gray cloud) — Vercel handles its own SSL/CDN
> - Backend A record must be **Proxied** (orange cloud) — Cloudflare provides WAF + DDoS protection

### 3d. Configure Vercel Custom Domain

1. Go to Vercel project → **Settings** → **Domains**
2. Add `brag.bobbyugbebor.store`
3. Vercel will verify DNS is correct (may take a few minutes)

### 3e. Set SSL/TLS Mode in Cloudflare

1. In Cloudflare dashboard, go to **SSL/TLS** → **Overview**
2. Set mode to **Full (Strict)** for `api-brag.bobbyugbebor.store`
   - Cloudflare validates Caddy's Let's Encrypt certificate
   - Ensures end-to-end encryption

### 3f. Configure Vercel Environment Variables

In Vercel Dashboard → your project → **Settings** → **Environment Variables**, add:

| Variable                 | Value                                   | Purpose                          |
| ------------------------ | --------------------------------------- | -------------------------------- |
| `NEXT_PUBLIC_SERVER_URL` | `https://brag.bobbyugbebor.store`       | Next.js allowed origins          |
| `NEXT_PUBLIC_API_URL`    | `https://api-brag.bobbyugbebor.store`   | Browser-side API calls           |
| `API_URL`                | `https://api-brag.bobbyugbebor.store`   | Server-side API calls            |
| `AUTH_SECRET`            | _(same as backend `/brag/auth_secret`)_ | JWT signing (must match backend) |
| `NEXTAUTH_URL`           | `https://brag.bobbyugbebor.store`       | NextAuth base URL                |
| `DATABASE_URL`           | _(your PostgreSQL connection string)_   | Prisma database                  |
| `RESEND_API_KEY`         | _(your Resend API key)_                 | Email sending                    |
| `EMAIL_FROM`             | `noreply@brag.bobbyugbebor.store`       | Sender email                     |
| `NEXT_PUBLIC_TESTING`    | `true`                                  | Enable test user mode            |
| `TESTING_CODE`           | `123456`                                | Test verification code           |

> **Critical:** `AUTH_SECRET` must match the backend's `/brag/auth_secret` SSM parameter exactly. Get it with:
>
> ```bash
> aws ssm get-parameter --name "/brag/auth_secret" --with-decryption --query 'Parameter.Value' --output text --region eu-north-1
> ```

After setting variables, **redeploy** the Vercel project.

---

## 7. Phase 4: Docker Build & Push

> **Where:** Your laptop

**What it does:** Builds the production Docker image and pushes it to ECR.

```bash
# From b-rag-engine2/ directory
cd b-rag-engine2

# Get ECR URL from Terraform output
ECR_URL=$(terraform output -raw ecr_repository_url)

# Login to ECR
aws ecr get-login-password --region eu-north-1 | \
  docker login --username AWS --password-stdin $ECR_URL

# Build production image
docker build -t b-rag-engine2:latest --target prod .

# Tag and push
docker tag b-rag-engine2:latest $ECR_URL:latest
docker push $ECR_URL:latest
```

---

## 8. Phase 5: Deploy Containers

> **Where:** EC2 instance (via SSH)

**What it does:** Creates a Docker network, runs the FastAPI container (internal only) and Caddy container (exposed on 80/443).

### 5a. SSH into EC2

```bash
ssh -i ~/.ssh/brag-key ec2-user@$(terraform output -raw ec2_public_ip)
```

### 5b. Create Docker Network

```bash
docker network create brag-net
```

This isolates the containers. Caddy can reach FastAPI via container name (`brag-api:8000`), but FastAPI is not exposed to the internet.

### 5c. Create Caddyfile

```bash
cat > /home/ec2-user/Caddyfile << 'EOF'
api-brag.bobbyugbebor.store {
    reverse_proxy brag-api:8000
}
EOF
```

> **Note:** `brag-api` is the Docker container name — Docker DNS resolves it automatically within the `brag-net` network.

### 5d. Login to ECR and Pull Image

```bash
ECR_URL="<your-ecr-url>.dkr.ecr.eu-north-1.amazonaws.com/b-rag-engine2"

aws ecr get-login-password --region eu-north-1 | \
  docker login --username AWS --password-stdin $ECR_URL

docker pull $ECR_URL:latest
```

### 5e. Fetch Secrets from SSM

```bash
export OPENROUTER_API_KEY=$(aws ssm get-parameter \
  --name /brag/openrouter_api_key --with-decryption \
  --query 'Parameter.Value' --output text --region eu-north-1)

export MONGODB_URI=$(aws ssm get-parameter \
  --name /brag/mongodb_uri --with-decryption \
  --query 'Parameter.Value' --output text --region eu-north-1)

export AUTH_SECRET=$(aws ssm get-parameter \
  --name /brag/auth_secret --with-decryption \
  --query 'Parameter.Value' --output text --region eu-north-1)

export CORS_ORIGINS=$(aws ssm get-parameter \
  --name /brag/cors_origins \
  --query 'Parameter.Value' --output text --region eu-north-1)
```

### 5f. Run FastAPI Container

```bash
docker run -d \
  --name brag-api \
  --network brag-net \
  --restart unless-stopped \
  -e OPENROUTER_API_KEY="$OPENROUTER_API_KEY" \
  -e MONGODB_URI="$MONGODB_URI" \
  -e AUTH_SECRET="$AUTH_SECRET" \
  -e CORS_ORIGINS="$CORS_ORIGINS" \
  $ECR_URL:latest
```

> **Note:** No `-p` flag — this container is internal only. It's reachable via `brag-api:8000` within the Docker network, but not from the internet.

### 5g. Run Caddy Container

```bash
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
```

**What happens:**
- Caddy starts and sees `api-brag.bobbyugbebor.store` in the Caddyfile
- It automatically requests a Let's Encrypt certificate (via Cloudflare proxy)
- Certificate is stored in the `caddy_data` Docker volume (persists across restarts)
- Auto-renews before expiration

### 5h. Verify Containers

```bash
docker ps
```

**Expected output:**
```
CONTAINER ID   IMAGE          STATUS         NAMES
<id>           caddy:latest   Up X minutes   caddy
<id>           <ECR_URL>      Up X minutes   brag-api
```

**Test locally:**
```bash
curl http://localhost/health
# Expected: {"status":"ok"}
```

---

## 9. Phase 6: Verify Deployment

> **Where:** Your laptop (exit SSH first)

```bash
exit
```

**Test the health endpoint (no auth required):**
```bash
curl https://api-brag.bobbyugbebor.store/health
# Expected: {"status":"ok"}
```

**Test the frontend:**
```
https://brag.bobbyugbebor.store
```

**Check container logs (via SSH):**
```bash
ssh -i ~/.ssh/brag-key ec2-user@$(terraform output -raw ec2_public_ip)
docker logs -f brag-api    # FastAPI logs
docker logs -f caddy       # Caddy logs
```

---

## 10. Phase 7: Ongoing Redeploy

When you update the backend code:

### 7a. Build and Push (your laptop)

```bash
cd b-rag-engine2
docker build -t b-rag-engine2:latest --target prod .
docker tag b-rag-engine2:latest $ECR_URL:latest
docker push $ECR_URL:latest
```

### 7b. Restart Container (EC2 via SSH)

```bash
ssh -i ~/.ssh/brag-key ec2-user@$(terraform output -raw ec2_public_ip)

# Fetch secrets (they're in env vars, need to re-fetch)
export OPENROUTER_API_KEY=$(aws ssm get-parameter --name /brag/openrouter_api_key --with-decryption --query 'Parameter.Value' --output text --region eu-north-1)
export MONGODB_URI=$(aws ssm get-parameter --name /brag/mongodb_uri --with-decryption --query 'Parameter.Value' --output text --region eu-north-1)
export AUTH_SECRET=$(aws ssm get-parameter --name /brag/auth_secret --with-decryption --query 'Parameter.Value' --output text --region eu-north-1)
export CORS_ORIGINS=$(aws ssm get-parameter --name /brag/cors_origins --query 'Parameter.Value' --output text --region eu-north-1)

# Pull new image
ECR_URL="<your-ecr-url>.dkr.ecr.eu-north-1.amazonaws.com/b-rag-engine2"
aws ecr get-login-password --region eu-north-1 | docker login --username AWS --password-stdin $ECR_URL
docker pull $ECR_URL:latest

# Stop and remove old container
docker stop brag-api && docker rm brag-api

# Start new container
docker run -d \
  --name brag-api \
  --network brag-net \
  --restart unless-stopped \
  -e OPENROUTER_API_KEY="$OPENROUTER_API_KEY" \
  -e MONGODB_URI="$MONGODB_URI" \
  -e AUTH_SECRET="$AUTH_SECRET" \
  -e CORS_ORIGINS="$CORS_ORIGINS" \
  $ECR_URL:latest
```

> **Note:** Caddy does NOT need to restart — it just proxies to `brag-api:8000` and the container name stays the same.

### 7c. Verify

```bash
curl https://api-brag.bobbyugbebor.store/health
# Expected: {"status":"ok"}
```

---

## 11. GitHub Actions CI/CD Setup

### OIDC Authentication (No IAM Keys)

GitHub Actions authenticates to AWS using OIDC (OpenID Connect) — no long-lived IAM keys.

**AWS Configuration:**
- **OIDC Provider:** `token.actions.githubusercontent.com`
- **IAM Role:** `github-actions-terraform`
- **Trust Policy:** Scoped to `repo:MDBBee@136184002/b-rag-engine2@1377622083:*` (immutable subject claims)

**Required IAM Permissions:**

| Service | Permissions | Purpose |
|---------|-------------|---------|
| **S3** | `GetObject`, `PutObject`, `ListBucket`, `DeleteObject` | Terraform state storage + lock file cleanup |
| **EC2** | `Describe*`, `Get*` | Read existing infrastructure for terraform plan |
| **ELB** | `Describe*` | Read load balancer state (if applicable) |
| **Auto Scaling** | `Describe*` | Read auto scaling groups (if applicable) |
| **ECR** | `DescribeRepositories`, `DescribeImages`, `ListTagsForResource` | Read ECR repository state for terraform plan |

**Why `s3:DeleteObject` is needed:** Terraform creates `.tflock` files in S3 to prevent concurrent modifications. After plan/apply completes, it must delete the lock file. Without this permission, locks remain stale and block subsequent runs.

**Why ECR permissions are needed:** Terraform reads all attributes of resources it manages, including ECR repositories and their tags, during `terraform plan` to detect drift.

### OIDC Setup Steps

**Step 1: Create OIDC Identity Provider**
1. AWS Console → IAM → Identity providers → Add provider
2. Select "OpenID Connect"
3. Provider URL: `https://token.actions.githubusercontent.com`
4. Click "Get thumbprint" (verifies the certificate)
5. Audience: `sts.amazonaws.com`
6. Click "Add provider"

**Step 2: Create IAM Role**
1. IAM → Roles → Create role
2. Select "Web identity" as trusted entity type
3. Identity provider: `token.actions.githubusercontent.com`
4. Audience: `sts.amazonaws.com`
5. GitHub organization: `MDBBee`
6. GitHub repository: `b-rag-engine2`
7. Role name: `github-actions-terraform`

**Step 3: Edit Trust Policy**

Replace the trust policy with:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::673318657554:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:MDBBee@136184002/b-rag-engine2@1377622083:*"
        }
      }
    }
  ]
}
```

**Step 4: Attach Permissions**

Create inline policy with:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:ListBucket",
        "s3:DeleteObject"
      ],
      "Resource": [
        "arn:aws:s3:::brag-terraform-state-1790495705",
        "arn:aws:s3:::brag-terraform-state-1790495705/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "ec2:Describe*",
        "ec2:Get*",
        "elasticloadbalancing:Describe*",
        "autoscaling:Describe*"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ecr:DescribeRepositories",
        "ecr:DescribeImages",
        "ecr:ListTagsForResource"
      ],
      "Resource": "*"
    }
  ]
}
```

**Step 5: Add GitHub Variable**
1. GitHub repo → Settings → Secrets and variables → Actions
2. Variables tab → New repository variable
3. Name: `AWS_ROLE_ARN`
4. Value: `arn:aws:iam::673318657554:role/github-actions-terraform`

### Workflow Structure

**File:** `.github/workflows/production-ci.yml`

**Triggers:**
- Push to `main` branch (only when `app/`, `Dockerfile`, `pyproject.toml`, or `uv.lock` change)
- Pull requests targeting `main`
- Manual trigger (`workflow_dispatch`)

**Jobs:**
1. **lint** (~30 seconds) — Runs Ruff linter on Python backend
2. **terraform-plan** (~30 seconds, PRs only) — Runs `terraform plan` and posts output as PR comment
3. **acceptance-test** (~10-15 minutes) — Robot Framework tests

**No deploy job** — all deployments are manual.

### Branch Protection Rules

**Ruleset Name:** Main Branch Protection  
**Target Branch:** `main`

**Enabled Rules:**
1. ✅ Require a pull request before merging — no direct pushes
2. ✅ Require status checks to pass — `lint` and `acceptance-test` must pass
3. ✅ Block force pushes — prevent history rewrites
4. ✅ Restrict deletions — prevent accidental branch deletion
5. ✅ Require linear history — clean git history (squash/rebase only)

---

## 12. Docker Optimization

### Multi-stage Build

- **Builder stage**: `python:3.11-slim` + `uv` for dependency installation
- **Runtime stage**: Clean `python:3.11-slim` with only the virtual environment and app code
- **Non-root user**: Runs as `app` user (security best practice)

### Final Image Size

~1.4-1.5 GB (down from 1.88 GB after optimization)

### Optimization Decisions

**Removed dependencies (saves ~360-500 MB):**

1. **`ipykernel`** — Jupyter kernel, not used in production (~50-80 MB)
2. **`langchain-community`** — Not imported anywhere (~10-20 MB)
3. **`markitdown[all]` → `markitdown[pdf,docx,pptx,xlsx]`** — Excluded unused extras (~300-400 MB)

### Image Size Breakdown

| Component | Size |
|-----------|------|
| `python:3.11-slim` base | ~120 MB |
| LangChain ecosystem | ~400-500 MB |
| OpenAI SDK + motor | ~50-100 MB |
| markitdown + pymupdf + core deps | ~150-200 MB |
| FastAPI + uvicorn + pydantic | ~50-100 MB |
| App code | < 1 MB |
| **Total** | **~1.4-1.5 GB** |

---

## 13. Troubleshooting

### Common Issues

| Problem                             | Check                                                                                   |
| ----------------------------------- | --------------------------------------------------------------------------------------- |
| EC2 not reachable                   | Security group allows 80/443? Instance running?                                         |
| SSL cert not issued                 | `docker logs caddy` — check for ACME errors                                             |
| Container not starting              | `docker logs brag-api` on EC2                                                           |
| Secrets not loading                 | IAM role attached to instance? SSM parameters exist?                                    |
| CORS errors                         | SSM parameter correct? Container has fresh env vars? See detailed troubleshooting below |
| Terraform state locked              | Check S3 bucket for `.tflock` file, delete if stale                                     |
| SSH connection refused              | Your IP in security group? Key pair correct?                                            |
| Caddy can't reach FastAPI           | Both containers on `brag-net`? `docker network inspect brag-net`                        |
| DNS not resolving                   | `dig api-brag.bobbyugbebor.store` — check Cloudflare proxy status                       |
| Vercel domain not verifying         | Check CNAME record: must be `b-rag-view.vercel.app` (no `https://`)                     |
| SSM ParameterAlreadyExists          | Run `terraform import` commands (see Phase 1 note)                                      |
| Frontend can't reach backend        | Check Vercel env vars: `NEXT_PUBLIC_API_URL` must be set and redeployed                 |
| Auth fails (401)                    | `AUTH_SECRET` in Vercel must match `/brag/auth_secret` in SSM exactly                   |
| CNAME "invalid content" error       | Remove `https://` and trailing `/` — use hostname only                                  |

### CORS Troubleshooting (Detailed)

**Symptom:** Browser console shows CORS errors.

**Root cause:** Container started with stale or incorrect `CORS_ORIGINS` env var.

**Diagnosis:**
1. Check SSM parameter (correct value):
   ```bash
   aws ssm get-parameter --name "/brag/cors_origins" --query 'Parameter.Value' --output text --region eu-north-1
   ```
2. Check container env vars (actual value):
   ```bash
   docker exec brag-api env | grep CORS
   ```
3. Test CORS headers:
   ```bash
   curl -H "Origin: https://brag.bobbyugbebor.store" -I https://api-brag.bobbyugbebor.store/health
   ```

**Fix:** Restart container with fresh env vars from SSM.

### Terraform State Lock Issues

**Error:** "Error acquiring the state lock" with PreconditionFailed

**Root Cause:** Previous workflow was cancelled or crashed, leaving a stale lock.

**Manual Fix:**
```bash
# Get lock ID from S3
aws s3 cp s3://brag-terraform-state-1790495705/b-rag-engine2/terraform.tfstate.tflock - --region eu-north-1 | jq -r '.ID'

# Force unlock
cd terraform
terraform force-unlock <LOCK_ID>
```

**Automatic Cleanup (Implemented):**
The workflow includes automatic lock cleanup on failure or cancellation.

---

## 14. Cost Summary

### AWS Free Tier (2026 Update)

| Account Created        | Free Tier Duration | What You Get                          |
| ---------------------- | ------------------ | ------------------------------------- |
| Before July 15, 2025   | 12 months          | t2.micro/t3.micro, 750 hrs IPv4/month |
| On/After July 15, 2025 | 6 months           | $100 credits + up to $100 more        |

### Monthly Costs

| Resource                       | During Free Tier   | After Free Tier        |
| ------------------------------ | ------------------ | ---------------------- |
| t3.micro EC2                   | Free               | ~$7.50                 |
| Public IPv4 address            | Free (750 hrs/mo)  | **~$3.60** ($0.005/hr) |
| ECR (1 image, ~500MB)          | ~$0.05             | ~$0.05                 |
| S3 (Terraform state, ~10KB)    | ~$0.01             | ~$0.01                 |
| SSM Parameter Store (4 params) | Free               | Free                   |
| VPC + Security Groups          | Free               | Free                   |
| **Total**                      | **~$0 - $0.06/mo** | **~$11.16/mo**         |

### External Services

| Service                | Cost                   |
| ---------------------- | ---------------------- |
| Vercel (frontend)      | Free tier (Hobby plan) |
| Cloudflare (DNS + WAF) | Free tier              |
| Namecheap (domain)     | ~$1-10/year            |

### Future Optimization: Cloudflare Tunnel

To eliminate the $3.60/month IPv4 cost:
1. Create Cloudflare Tunnel
2. Install cloudflared on EC2
3. Remove public IP, close ports 80/443
4. Traffic flows: user → Cloudflare → tunnel → EC2 (private)

This reduces ongoing costs to ~$7.56/month (EC2 + ECR + S3).

---

## 15. Quick Reference Commands

```bash
# Get EC2 IP
terraform output ec2_public_ip

# SSH into instance
ssh -i ~/.ssh/brag-key ec2-user@$(terraform output -raw ec2_public_ip)

# View FastAPI logs
docker logs -f brag-api

# View Caddy logs
docker logs -f caddy

# Restart FastAPI container (after pulling new image)
docker stop brag-api && docker rm brag-api
# ... then docker run (see Phase 7b)

# Check SSM parameters
aws ssm get-parameters-by-path --path /brag --with-decryption --region eu-north-1

# Check Docker network
docker network inspect brag-net

# Test health endpoint
curl https://api-brag.bobbyugbebor.store/health

# Get lock ID from S3 (for manual unlock)
aws s3 cp s3://brag-terraform-state-1790495705/b-rag-engine2/terraform.tfstate.tflock - --region eu-north-1 | jq -r '.ID'

# Force unlock terraform state
cd terraform && terraform force-unlock <LOCK_ID>
```
