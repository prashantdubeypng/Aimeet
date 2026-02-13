# Deploy to Render.com

## Prerequisites
- GitHub account with this repo pushed
- Render.com account (free signup)
- All API keys ready (Agora, AssemblyAI, Google, Qdrant, Pusher)

## Deployment Steps

### 1. Push Code to GitHub
```bash
git add .
git commit -m "Add Render deployment config"
git push origin master
```

### 2. Create New Web Service on Render
1. Go to https://dashboard.render.com/
2. Click **"New +"** → **"Blueprint"**
3. Connect your GitHub repository: `prashantdubeypng/Aimeet`
4. Render will detect `render.yaml` automatically
5. Click **"Apply"**

### 3. Set Environment Variables
In Render Dashboard, go to your web service → **Environment** tab and add:

**Required Variables:**
```bash
DJANGO_ALLOWED_HOSTS=your-app-name.onrender.com
AWS_ACCESS_KEY_ID=your_aws_key
AWS_SECRET_ACCESS_KEY=your_aws_secret
AWS_STORAGE_BUCKET_NAME=your_bucket_name
AGORA_APP_ID=your_agora_app_id
AGORA_APP_CERTIFICATE=your_agora_cert
AGORA_CUSTOMER_ID=your_agora_customer_id
AGORA_CUSTOMER_SECRET=your_agora_customer_secret
ASSEMBLYAI_API_KEY=your_assemblyai_key
GOOGLE_API_KEY=your_google_api_key
QDRANT_URL=https://your-qdrant-instance.qdrant.io:6333
QDRANT_API_KEY=your_qdrant_key
PUSHER_APP_ID=your_pusher_app_id
PUSHER_KEY=your_pusher_key
PUSHER_SECRET=your_pusher_secret
PUSHER_CLUSTER=your_pusher_cluster
```

**Auto-Generated (already set by render.yaml):**
- `DJANGO_SECRET_KEY` ✓
- `DATABASE_URL` ✓
- `REDIS_URL` ✓

### 4. Wait for Deployment
- Render will automatically:
  - Install dependencies
  - Run migrations
  - Collect static files
  - Start Daphne server
  - Start Django-Q worker

### 5. Create Superuser (First Time)
After deployment, go to **Shell** tab in Render Dashboard:
```bash
cd videocaller
python manage.py createsuperuser
```

### 6. Test Your App
Visit: `https://your-app-name.onrender.com`

## Render Services Created

### 1. Web Service (Daphne)
- Runs Django/WebSocket server
- Auto-scales on demand
- **Cost:** Free tier (500 hrs/month) or Starter ($7/month)

### 2. Worker Service (Django-Q)
- Processes background tasks (transcription, embeddings)
- **Cost:** Starter ($7/month)

### 3. PostgreSQL Database
- Persistent storage for meetings/users
- **Cost:** Free for 90 days, then $7/month

### 4. Redis
- Cache + Django-Q broker
- **Cost:** Free for 90 days, then $7/month

**Total Cost After Free Trial:** ~$21/month

## Free Tier Limitations
- Web service sleeps after 15 min inactivity (50 sec cold start)
- 500 build hours/month
- 100 GB bandwidth/month

## Custom Domain (Optional)
1. Go to **Settings** → **Custom Domain**
2. Add your domain: `yourdomain.com`
3. Update DNS CNAME to point to Render

## Monitoring
- **Logs:** Dashboard → Logs tab
- **Metrics:** Dashboard → Metrics tab
- **Health Check:** https://your-app.onrender.com/api/health/google/

## Troubleshooting

### Service won't start
Check logs for errors:
```bash
# Common issues:
- Missing environment variables
- PostgreSQL connection failed
- Redis connection failed
```

### WebSocket not working
Ensure:
- Daphne is running (not Gunicorn)
- ALLOWED_HOSTS includes your domain
- CSRF_TRUSTED_ORIGINS is set

### Static files not loading
Run manually:
```bash
cd videocaller
python manage.py collectstatic --no-input
```

## Rollback
If deployment fails:
1. Go to **Events** tab
2. Find previous successful deploy
3. Click **"Redeploy"**

## Auto-Deploy on Push
Render automatically deploys when you push to `master` branch.

Disable: **Settings** → **Auto-Deploy** → OFF

## Scale Up
To handle more users:
1. **Settings** → **Instance Type** → Select higher tier
2. Add more worker instances
3. Upgrade PostgreSQL/Redis plans

---

**Support:** Check logs in Render Dashboard or visit https://render.com/docs
