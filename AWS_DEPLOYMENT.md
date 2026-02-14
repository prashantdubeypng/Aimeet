# AWS Deployment Guide - Complete Steps

## Prerequisites

### 1. AWS Account Setup
- [ ] Create AWS account at https://aws.amazon.com
- [ ] Enable billing alerts
- [ ] Create IAM user with admin access (don't use root)
- [ ] Install AWS CLI: `aws configure`

### 2. Local Requirements
- [ ] Git installed
- [ ] Docker installed (for testing containers)
- [ ] AWS CLI installed
- [ ] EB CLI installed: `pip install awsebcli`

---

## Step 1: Prepare Your Application

### A. Create Production Requirements
```bash
# Already done - verify requirements.txt has:
# - psycopg2-binary (PostgreSQL)
# - gunicorn (WSGI server)
# - whitenoise (static files)
# - dj-database-url (DB config)
```

### B. Create Dockerfile
```dockerfile
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy project
COPY videocaller/ ./videocaller/

# Collect static files
WORKDIR /app/videocaller
RUN python manage.py collectstatic --no-input

# Run migrations and start server
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "videocaller.asgi:application"]
```

### C. Create .dockerignore
```
env/
venv/
*.pyc
__pycache__/
db.sqlite3
.env
.git/
.github/
*.md
build.sh
```

---

## Step 2: AWS Services Setup

### A. Create RDS PostgreSQL Database

1. **Go to RDS Console**
   - Navigate to https://console.aws.amazon.com/rds

2. **Create Database**
   ```
   Choose: PostgreSQL 15
   Template: Free tier (or Production for real apps)
   
   Settings:
   - DB instance identifier: aimeet-db
   - Master username: postgres
   - Master password: [generate strong password]
   
   Instance configuration:
   - DB instance class: db.t3.micro (free tier)
   
   Storage:
   - Allocated storage: 20 GB
   - Storage autoscaling: Enable
   
   Connectivity:
   - VPC: Default
   - Public access: Yes (for now, restrict later)
   - VPC security group: Create new
   - Database port: 5432
   
   Database authentication:
   - Password authentication
   
   Additional configuration:
   - Initial database name: aimeet
   - Automated backups: Enable (7 days retention)
   ```

3. **Note the endpoint** (e.g., `aimeet-db.xxxxx.us-east-1.rds.amazonaws.com`)

### B. Create ElastiCache Redis

1. **Go to ElastiCache Console**
   - Navigate to https://console.aws.amazon.com/elasticache

2. **Create Redis Cluster**
   ```
   Cluster mode: Disabled
   Engine: Redis 7.x
   
   Cluster info:
   - Name: aimeet-redis
   - Engine version: 7.0
   - Port: 6379
   - Node type: cache.t3.micro
   - Number of replicas: 0 (for dev/test)
   
   Subnet group: Default
   Security groups: Create new or use default
   ```

3. **Note the endpoint** (e.g., `aimeet-redis.xxxxx.cache.amazonaws.com:6379`)

### C. Create S3 Bucket (Already exists for recordings)

1. **Verify your S3 bucket** from AGORA_STORAGE_BUCKET_NAME
2. **Set CORS policy** if needed for uploads

### D. Create Application Load Balancer (ALB)

1. **Go to EC2 > Load Balancers**

2. **Create ALB**
   ```
   Type: Application Load Balancer
   Name: aimeet-alb
   Scheme: Internet-facing
   IP address type: IPv4
   
   Network mapping:
   - VPC: Default
   - Availability Zones: Select 2+ zones
   
   Security groups: Create new
   - Name: aimeet-alb-sg
   - Inbound: HTTP (80), HTTPS (443)
   
   Listeners:
   - HTTP:80 → Forward to target group (create below)
   - HTTPS:443 → Forward to target group (needs SSL cert)
   ```

3. **Create Target Group**
   ```
   Type: Instances
   Name: aimeet-targets
   Protocol: HTTP
   Port: 8000
   VPC: Default
   
   Health check:
   - Protocol: HTTP
   - Path: /
   - Interval: 30 seconds
   ```

### E. Request SSL Certificate (ACM)

1. **Go to Certificate Manager**
   - Region: Same as ALB

2. **Request Certificate**
   ```
   Domain: yourdomain.com
   Validation: DNS (recommended)
   
   Add to DNS:
   - Copy CNAME records to your domain registrar
   - Wait for validation (~5-30 minutes)
   ```

3. **Attach to ALB**
   - Edit HTTPS:443 listener
   - Select your certificate

---

## Step 3: Deploy Application

### Option A: Deploy with Elastic Beanstalk (Easiest)

#### A.1 Initialize EB
```bash
cd c:\dev\Django-VIdeocall-App

# Initialize
eb init

# Prompts:
# Region: us-east-1
# Application name: aimeet
# Platform: Docker
# SSH: Yes (generate keypair)
```

#### A.2 Create Environment
```bash
eb create production

# Environment name: aimeet-production
# DNS CNAME: aimeet (will be aimeet.us-east-1.elasticbeanstalk.com)
# Load balancer: Application
```

#### A.3 Configure Environment Variables
```bash
eb setenv \
  DJANGO_SECRET_KEY="your-secret-key" \
  DJANGO_DEBUG="false" \
  DJANGO_ALLOWED_HOSTS="aimeet-production.us-east-1.elasticbeanstalk.com,yourdomain.com" \
  DATABASE_URL="postgresql://postgres:password@aimeet-db.xxxxx.us-east-1.rds.amazonaws.com:5432/aimeet" \
  REDIS_URL="redis://aimeet-redis.xxxxx.cache.amazonaws.com:6379/0" \
  AWS_ACCESS_KEY_ID="your-key" \
  AWS_SECRET_ACCESS_KEY="your-secret" \
  AWS_STORAGE_BUCKET_NAME="your-bucket" \
  AGORA_APP_ID="..." \
  AGORA_APP_Certificate="..." \
  ASSEMBLYAI_API_KEY="..." \
  GOOGLE_API_KEY="..." \
  QDRANT_URL="..." \
  QDRANT_API_KEY="..." \
  PUSHER_APP_ID="..." \
  PUSHER_KEY="..." \
  PUSHER_SECRET="..." \
  PUSHER_CLUSTER="..."
```

#### A.4 Deploy
```bash
eb deploy
```

#### A.5 Run Migrations
```bash
eb ssh
cd /var/app/current/videocaller
python manage.py migrate
python manage.py createsuperuser
exit
```

### Option B: Deploy with ECS Fargate (More scalable)

#### B.1 Build and Push Docker Image
```bash
# Build
docker build -t aimeet:latest .

# Tag for ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com

# Create repository
aws ecr create-repository --repository-name aimeet --region us-east-1

# Tag and push
docker tag aimeet:latest YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/aimeet:latest
docker push YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/aimeet:latest
```

#### B.2 Create ECS Cluster
```bash
aws ecs create-cluster --cluster-name aimeet-cluster --region us-east-1
```

#### B.3 Create Task Definition
Create `ecs-task-definition.json`:
```json
{
  "family": "aimeet-task",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "512",
  "memory": "1024",
  "containerDefinitions": [
    {
      "name": "aimeet-web",
      "image": "YOUR_ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/aimeet:latest",
      "portMappings": [
        {
          "containerPort": 8000,
          "protocol": "tcp"
        }
      ],
      "environment": [
        {"name": "DJANGO_DEBUG", "value": "false"}
      ],
      "secrets": [
        {"name": "DJANGO_SECRET_KEY", "valueFrom": "arn:aws:secretsmanager:..."},
        {"name": "DATABASE_URL", "valueFrom": "arn:aws:secretsmanager:..."}
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/aimeet",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
```

Register:
```bash
aws ecs register-task-definition --cli-input-json file://ecs-task-definition.json
```

#### B.4 Create ECS Service
```bash
aws ecs create-service \
  --cluster aimeet-cluster \
  --service-name aimeet-service \
  --task-definition aimeet-task \
  --desired-count 2 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx,subnet-yyy],securityGroups=[sg-xxx],assignPublicIp=ENABLED}" \
  --load-balancers "targetGroupArn=arn:aws:elasticloadbalancing:...,containerName=aimeet-web,containerPort=8000"
```

### Option C: Deploy on EC2 (Manual, most control)

#### C.1 Launch EC2 Instance
```
AMI: Ubuntu 22.04 LTS
Instance type: t3.medium
Security group: Allow 22 (SSH), 8000 (Daphne), 80, 443
Key pair: Create/select for SSH
Storage: 30 GB
```

#### C.2 SSH and Setup
```bash
ssh -i your-key.pem ubuntu@your-ec2-ip

# Update system
sudo apt update && sudo apt upgrade -y

# Install dependencies
sudo apt install -y python3.11 python3.11-venv python3-pip git nginx postgresql-client redis-tools

# Clone repo
git clone https://github.com/prashantdubeypng/Aimeet.git
cd Aimeet

# Create virtual environment
python3.11 -m venv env
source env/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Set environment variables
sudo nano /etc/environment
# Add all env vars

# Run migrations
cd videocaller
python manage.py migrate
python manage.py createsuperuser
python manage.py collectstatic --no-input

# Create systemd service
sudo nano /etc/systemd/system/aimeet.service
```

`/etc/systemd/system/aimeet.service`:
```ini
[Unit]
Description=AIMeet Daphne Service
After=network.target

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/Aimeet/videocaller
EnvironmentFile=/etc/environment
ExecStart=/home/ubuntu/Aimeet/env/bin/daphne -b 0.0.0.0 -p 8000 videocaller.asgi:application
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
# Start service
sudo systemctl daemon-reload
sudo systemctl enable aimeet
sudo systemctl start aimeet

# Configure Nginx
sudo nano /etc/nginx/sites-available/aimeet
```

`/etc/nginx/sites-available/aimeet`:
```nginx
upstream django {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name yourdomain.com;

    location / {
        proxy_pass http://django;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static/ {
        alias /home/ubuntu/Aimeet/videocaller/staticfiles/;
    }

    location /media/ {
        alias /home/ubuntu/Aimeet/videocaller/media/;
    }
}
```

```bash
# Enable site
sudo ln -s /etc/nginx/sites-available/aimeet /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx

# Install SSL (Let's Encrypt)
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com
```

---

## Step 4: Configure Domain (Route 53)

### A. Create Hosted Zone
1. Go to Route 53
2. Create hosted zone: `yourdomain.com`
3. Note the nameservers

### B. Update Domain Registrar
1. Go to your domain registrar (GoDaddy, Namecheap, etc.)
2. Update nameservers to Route 53's NS records

### C. Create DNS Records
```
Type: A
Name: @ (or blank)
Value: [ALB DNS or EC2 Elastic IP]
TTL: 300

Type: CNAME
Name: www
Value: yourdomain.com
TTL: 300
```

---

## Step 5: Setup CloudWatch Monitoring

### A. Enable CloudWatch Logs
```bash
# For EB
eb logs --cloudwatch-logs enable

# For ECS - already enabled in task definition

# For EC2 - install CloudWatch agent
wget https://s3.amazonaws.com/amazoncloudwatch-agent/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
sudo dpkg -i amazon-cloudwatch-agent.deb
```

### B. Create Alarms
```
Metric: RDSCPUUtilization > 80%
Metric: ALBTargetResponseTime > 2s
Metric: EC2StatusCheckFailed
Action: Send SNS notification
```

---

## Step 6: Setup Auto-Scaling (Optional)

### For EB
```bash
eb scale 2  # Start with 2 instances

# Configure auto-scaling
eb config
# Set min instances: 2
# Set max instances: 10
# Scaling trigger: CPU > 70%
```

### For ECS
```bash
aws application-autoscaling register-scalable-target \
  --service-namespace ecs \
  --scalable-dimension ecs:service:DesiredCount \
  --resource-id service/aimeet-cluster/aimeet-service \
  --min-capacity 2 \
  --max-capacity 10
```

---

## Step 7: Backup Strategy

### A. RDS Automated Backups
- Already enabled (7-day retention)
- Take manual snapshots before major changes

### B. S3 Versioning
```bash
aws s3api put-bucket-versioning \
  --bucket your-bucket \
  --versioning-configuration Status=Enabled
```

### C. Database Snapshots
```bash
# Manual snapshot
aws rds create-db-snapshot \
  --db-instance-identifier aimeet-db \
  --db-snapshot-identifier aimeet-db-backup-$(date +%Y%m%d)
```

---

## Step 8: Security Hardening

### A. IAM Roles
- Create role for EC2/ECS with minimal permissions
- Don't use root credentials

### B. Security Groups
```
RDS Security Group:
- Inbound: PostgreSQL (5432) from EC2/ECS security group only

Redis Security Group:
- Inbound: Redis (6379) from EC2/ECS security group only

EC2/ECS Security Group:
- Inbound: HTTP/HTTPS from ALB only
- Inbound: SSH from your IP only

ALB Security Group:
- Inbound: HTTP (80), HTTPS (443) from 0.0.0.0/0
```

### C. Enable WAF (Optional)
```
Go to AWS WAF
Create Web ACL
Attach to ALB
Enable managed rule sets:
- AWS-AWSManagedRulesCommonRuleSet
- AWS-AWSManagedRulesKnownBadInputsRuleSet
```

---

## Step 9: CI/CD with GitHub Actions

Already configured in `.github/workflows/deploy.yml` but update for AWS:

```yaml
name: Deploy to AWS

on:
  push:
    branches: [master]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-east-1
      
      - name: Deploy to Elastic Beanstalk
        run: |
          pip install awsebcli
          eb deploy production --staged
```

---

## Step 10: Cost Optimization

### Development/Testing
```
RDS: db.t3.micro (Free tier eligible)
ElastiCache: cache.t3.micro
EC2: t3.small
Total: ~$50-70/month
```

### Production (Low traffic)
```
RDS: db.t3.small with Multi-AZ
ElastiCache: cache.t3.small with replication
EC2/ECS: 2x t3.medium
ALB: ~$16/month
Total: ~$150-200/month
```

### Cost Saving Tips
- Use Reserved Instances (save 30-60%)
- Enable RDS auto-scaling storage
- Use S3 Intelligent-Tiering
- Set CloudWatch alarms for billing
- Use Spot Instances for non-critical workloads

---

## Troubleshooting

### Database Connection Issues
```bash
# Test from EC2
telnet aimeet-db.xxxxx.rds.amazonaws.com 5432

# Check security groups
# Ensure EC2 security group is allowed in RDS inbound rules
```

### Static Files Not Loading
```bash
# Ensure STATIC_ROOT is set
# Run collectstatic
python manage.py collectstatic --no-input

# Check Nginx config
# Verify WhiteNoise middleware order
```

### WebSocket Connection Fails
```bash
# Ensure ALB supports WebSocket
# Check target group health
# Verify Daphne is running (not Gunicorn)
```

---

## Final Checklist

- [ ] RDS database created and accessible
- [ ] Redis cluster running
- [ ] S3 bucket configured
- [ ] Application deployed (EB/ECS/EC2)
- [ ] Migrations run
- [ ] Superuser created
- [ ] SSL certificate installed
- [ ] Domain pointed to ALB/EC2
- [ ] Environment variables set
- [ ] CloudWatch monitoring enabled
- [ ] Backups configured
- [ ] Security groups hardened
- [ ] CI/CD pipeline tested
- [ ] Cost alerts set

---

## Quick Deployment Commands

```bash
# Elastic Beanstalk (recommended for quick start)
eb init
eb create production
eb setenv [all env vars]
eb deploy
eb ssh
cd /var/app/current/videocaller
python manage.py migrate
python manage.py createsuperuser

# Access logs
eb logs

# Check status
eb status

# Terminate (be careful!)
eb terminate production
```

---

**Estimated Setup Time:**
- EB Deploy: 2-3 hours
- ECS Deploy: 4-6 hours
- EC2 Manual: 6-8 hours

**Support Resources:**
- AWS Documentation: https://docs.aws.amazon.com
- Elastic Beanstalk Guide: https://docs.aws.amazon.com/elasticbeanstalk
- Django Deployment: https://docs.djangoproject.com/en/4.1/howto/deployment/

Good luck with your AWS deployment! 🚀
