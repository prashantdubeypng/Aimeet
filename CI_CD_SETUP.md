# CI/CD Setup Guide

## Overview
This project uses **GitHub Actions** for Continuous Integration and Continuous Deployment.

---

## Workflows

### 1. **CI - Tests and Checks** (`ci.yml`)
**Triggers:** Push or PR to `master` or `develop`

**What it does:**
- ✅ Runs Python linting (flake8)
- ✅ Checks code formatting (black, isort)
- ✅ Runs Django tests
- ✅ Checks for missing migrations
- ✅ Security vulnerability scan
- ✅ Builds and validates static files

**Services:**
- PostgreSQL 15
- Redis 7

---

### 2. **CD - Deploy to Render** (`deploy.yml`)
**Triggers:** Push to `master` or manual trigger

**What it does:**
- 🚀 Automatically deploys to Render
- 🔍 Runs post-deployment health check
- 📢 Notifies deployment status

---

### 3. **Manual Deploy** (`manual-deploy.yml`)
**Triggers:** Manual trigger via GitHub Actions UI

**What it does:**
- 🚀 Deploy to production or staging
- 🔍 Post-deployment health check

**Usage:**
1. Go to **Actions** tab in GitHub
2. Select "Manual Deploy"
3. Click **Run workflow**
4. Choose environment (production/staging)

---

### 4. **Weekly Security Scan** (`security.yml`)
**Triggers:** Every Monday at 9 AM UTC or manual trigger

**What it does:**
- 🔒 Scans dependencies for vulnerabilities (Safety)
- 🔒 Code security analysis (Bandit)
- 📊 Uploads reports as artifacts
- 🚨 Creates GitHub issue if vulnerabilities found

---

## Setup Instructions

### 1. Configure GitHub Secrets
Go to **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

**Required secrets:**

```bash
RENDER_SERVICE_ID        # Get from Render dashboard
RENDER_API_KEY           # Generate at https://dashboard.render.com/u/settings#api-keys
RENDER_APP_URL           # Your app URL (e.g., https://aimeet.onrender.com)
```

**Optional (for tests):**
```bash
GOOGLE_API_KEY           # For running integration tests
QDRANT_URL               # For running RAG tests
QDRANT_API_KEY           # For Qdrant tests
```

### 2. Get Render Credentials

#### **Service ID:**
1. Go to https://dashboard.render.com
2. Open your web service
3. URL will look like: `https://dashboard.render.com/web/srv-xxxxxxxxxxxxx`
4. Copy the `srv-xxxxxxxxxxxxx` part

#### **API Key:**
1. Go to https://dashboard.render.com/u/settings#api-keys
2. Click **Generate New Key**
3. Name it: `GitHub Actions`
4. Copy the key (only shown once!)

### 3. Enable GitHub Actions
1. Go to your repo → **Actions** tab
2. Click **"I understand my workflows, go ahead and enable them"**

---

## How Auto-Deploy Works

```
Push to master
    ↓
GitHub Actions triggers
    ↓
Runs CI tests (optional, can skip)
    ↓
Calls Render API to deploy
    ↓
Render pulls latest code
    ↓
Runs build.sh (migrations, static files)
    ↓
Restarts services
    ↓
Health check runs
    ↓
✅ Deployment complete!
```

---

## Branch Protection (Recommended)

### Protect `master` branch:
1. Go to **Settings** → **Branches** → **Add rule**
2. Branch name pattern: `master`
3. Enable:
   - ✅ Require a pull request before merging
   - ✅ Require status checks to pass before merging
     - Select: `test`, `security`, `build`
   - ✅ Require branches to be up to date before merging
4. Save changes

Now all pushes to `master` must pass CI checks!

---

## Monitoring Deployments

### View deployment status:
1. Go to **Actions** tab
2. Click on any workflow run
3. View logs for each step

### View deployment history:
1. Go to Render Dashboard
2. Select your service
3. Click **Events** tab

---

## Rollback a Deployment

### Quick rollback on Render:
1. Go to Render Dashboard → Your service
2. Click **Events** tab
3. Find last working deployment
4. Click **"Redeploy"**

### Rollback via GitHub:
```bash
# Revert the commit
git revert <bad-commit-hash>
git push origin master

# Auto-deploys the previous working version
```

---

## Manual Deployment

### Via GitHub Actions:
1. Go to **Actions** tab
2. Select "Manual Deploy" workflow
3. Click **Run workflow**
4. Choose environment
5. Click **Run workflow**

### Via Render Dashboard:
1. Go to your service
2. Click **Manual Deploy**
3. Select branch: `master`
4. Click **Deploy**

---

## Disable Auto-Deploy

### Option 1: In GitHub
Disable the workflow:
```bash
git mv .github/workflows/deploy.yml .github/workflows/deploy.yml.disabled
git commit -m "Disable auto-deploy"
git push
```

### Option 2: In Render
1. Go to your service → **Settings**
2. Find "Auto-Deploy"
3. Toggle **OFF**

---

## Troubleshooting

### CI tests failing?
- Check the **Actions** tab logs
- Common issues:
  - Missing migrations
  - Linting errors
  - Test failures

### Deployment failing?
- Check Render Dashboard → **Logs**
- Common issues:
  - Missing environment variables
  - Database migration errors
  - Build script errors

### Health check failing?
- App may still be starting (wait 2-3 minutes)
- Check if `GOOGLE_API_KEY` is set correctly
- Visit the health endpoint manually

---

## Environment Variables in CI

The CI workflow uses test values for:
- `DATABASE_URL` → PostgreSQL service
- `REDIS_URL` → Redis service
- `DJANGO_SECRET_KEY` → Test key

Real credentials (from GitHub Secrets) are only used for:
- Integration tests (optional)
- Deployment to Render

---

## Advanced: Staging Environment

### Create staging service on Render:
1. Duplicate your web service
2. Name it: `aimeet-staging`
3. Set branch: `develop`

### Add staging workflow:
```yaml
# .github/workflows/deploy-staging.yml
name: Deploy to Staging

on:
  push:
    branches: [ develop ]

jobs:
  deploy:
    # ... same as deploy.yml but with staging secrets
```

### Add staging secrets:
```
RENDER_STAGING_SERVICE_ID
RENDER_STAGING_APP_URL
```

---

## Cost of CI/CD

**GitHub Actions:**
- Public repos: **FREE** unlimited
- Private repos: 2,000 minutes/month free (more than enough)

**Total cost:** $0 for public repos! 🎉

---

## Badge for README

Add this to your README.md to show build status:

```markdown
![CI](https://github.com/prashantdubeypng/Aimeet/workflows/CI%20-%20Tests%20and%20Checks/badge.svg)
![Deploy](https://github.com/prashantdubeypng/Aimeet/workflows/CD%20-%20Deploy%20to%20Render/badge.svg)
```

---

**Need help?** Check the workflow logs in the Actions tab!
