# Agora Cloud Recording Setup Guide

This guide explains how to set up and use Agora Cloud Recording with AWS S3 storage for your video meeting app.

## Prerequisites

1. **Agora Account** - You need:
   - Agora App ID (already configured)
   - Agora App Certificate (already configured)
   - **NEW: Agora Cloud Recording credentials**
     - Customer ID
     - Customer Secret
     - Get these from: https://console.agora.io/

2. **AWS Account** - You need:
   - AWS Access Key ID
   - AWS Secret Access Key
   - S3 Bucket Name
   - AWS Region

## Step 1: Get Agora Cloud Recording Credentials

1. Go to https://console.agora.io/
2. Navigate to your project
3. Go to "Cloud Recording" section
4. Enable Cloud Recording if not already enabled
5. Get your **Customer ID** and **Customer Secret**

## Step 2: Create AWS S3 Bucket

1. Go to AWS Console: https://console.aws.amazon.com/s3/
2. Create a new bucket:
   ```
   - Bucket name: your-meeting-recordings (choose your own name)
   - Region: us-east-1 (or your preferred region)
   - Uncheck "Block all public access" if you want public URLs
     OR keep it private and use presigned URLs (recommended)
   ```

3. Create IAM User for S3 Access:
   - Go to IAM → Users → Create user
   - User name: `agora-recording-user`
   - Attach policy: `AmazonS3FullAccess` or create a custom policy:
   
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": [
           "s3:PutObject",
           "s3:GetObject",
           "s3:ListBucket"
         ],
         "Resource": [
           "arn:aws:s3:::your-bucket-name",
           "arn:aws:s3:::your-bucket-name/*"
         ]
       }
     ]
   }
   ```

4. Create Access Keys:
   - Go to user → Security credentials → Create access key
   - Choose "Application running outside AWS"
   - Save the Access Key ID and Secret Access Key

## Step 3: Update Environment Variables

Edit `.env` file and add your credentials:

```env
# Agora Cloud Recording credentials
AGORA_CUSTOMER_ID='your_customer_id_here'
AGORA_CUSTOMER_SECRET='your_customer_secret_here'
AGORA_RECORDING_REGION='NA'  # NA, EU, AP, or CN

# AWS S3 Configuration
AWS_ACCESS_KEY_ID='your_aws_access_key_here'
AWS_SECRET_ACCESS_KEY='your_aws_secret_key_here'
AWS_STORAGE_BUCKET_NAME='your_bucket_name_here'
AWS_S3_REGION_NAME='us-east-1'  # Match your bucket region
```

**Important:** Never commit `.env` to version control!

## Step 4: Install Dependencies

```bash
pip install -r requirements.txt
```

New packages added:
- `boto3` - AWS SDK for Python (S3 uploads)
- `requests` - HTTP library (Agora API calls)

## Step 5: Run Database Migrations

The MeetingRoom model has been updated with new fields for cloud recording:

```bash
cd videocaller
python manage.py makemigrations
python manage.py migrate
```

## Step 6: Test the Setup

1. Start the server:
   ```bash
   python manage.py runserver
   ```

2. Create a meeting as a host

3. Click "Start Recording" (only visible to host)

4. The recording will:
   - Start automatically on Agora's servers
   - Save directly to your S3 bucket
   - Generate both HLS (for streaming) and MP4 (for download)

5. Click "Stop Recording" to end

6. Recording files will be in S3 at:
   ```
   s3://your-bucket-name/recordings/{room_id}/M{session_id}.mp4
   ```

## How It Works

### Architecture

```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│   Meeting   │──────│ Agora Cloud  │──────│   AWS S3    │
│  Attendees  │      │  Recording   │      │   Bucket    │
└─────────────┘      └──────────────┘      └─────────────┘
     │                      │                      │
     │ Audio/Video          │ Recording Bot        │ Uploaded
     │ Streams              │ Joins & Records      │ Files
     └──────────────────────┴──────────────────────┘
```

### Recording Process

1. **Start Recording:**
   - Host clicks "Start Recording"
   - Backend acquires resource ID from Agora
   - Starts recording session with S3 credentials
   - Recording bot joins the channel
   - Records all audio/video streams

2. **During Recording:**
   - Agora servers record in real-time
   - No bandwidth usage from your server
   - All participants are recorded automatically

3. **Stop Recording:**
   - Host clicks "Stop Recording"
   - Backend stops the recording session
   - Agora uploads files to S3
   - S3 URL is saved in database

### File Formats

Recordings are saved in two formats:
- **HLS (.m3u8)** - For live streaming/playback
- **MP4 (.mp4)** - For download and archival

## Features Implemented

### ✅ Host-Only Recording Permissions
- Only the meeting host can start/stop recording
- Recording button disabled for participants
- Backend enforces permission checks

### ✅ Agora Cloud Recording Integration
- Automatic recording of all streams
- No client-side processing required
- Professional-grade recording quality

### ✅ AWS S3 Storage
- Secure cloud storage
- Scalable and reliable
- Pre-signed URLs for private access

### ✅ Database Tracking
- Recording status (not_started, recording, completed, failed)
- S3 URLs for recordings
- Recording duration
- Resource IDs for query operations

## API Endpoints

### Start Recording
```
POST /meeting/{room_code}/start-recording/
Authorization: Required (Host only)
Response: { "message": "Recording started", "sid": "...", "resourceId": "..." }
```

### Stop Recording
```
POST /meeting/{room_code}/stop-recording/
Authorization: Required (Host only)
Response: { "message": "Recording stopped", "fileList": [...], "s3_url": "..." }
```

### Query Recording Status
```
GET /meeting/{room_code}/query-recording/
Authorization: Required
Response: { "status": "recording", "serverResponse": {...} }
```

## Troubleshooting

### Error: "Failed to acquire recording resource"
- Check Agora Customer ID and Secret
- Verify Cloud Recording is enabled in Agora Console
- Check AGORA_RECORDING_REGION matches your account region

### Error: "Failed to start recording"
- Verify S3 bucket exists
- Check AWS credentials are correct
- Ensure bucket region matches AWS_S3_REGION_NAME
- Check IAM user has S3 write permissions

### Recording files not appearing in S3
- Wait 1-2 minutes after stopping (upload takes time)
- Check S3 bucket in correct region
- Verify bucket name in settings
- Check CloudWatch logs in Agora Console

### Permission denied errors
- Ensure you're logged in as the meeting host
- Check Django authentication is working
- Verify is_host context variable in template

## Cost Considerations

### Agora Cloud Recording Pricing
- Charged per minute of recording
- Different rates for audio-only vs video
- Check: https://www.agora.io/en/pricing/

### AWS S3 Pricing
- Storage: ~$0.023/GB/month (us-east-1)
- Data transfer: First 100GB free/month
- Check: https://aws.amazon.com/s3/pricing/

### Estimated Costs (Example)
- 1 hour meeting, 5 participants, video recording:
  - Agora: ~$1-2 (varies by region)
  - S3 Storage: ~1GB = $0.023/month
  - Total: ~$1-2 + minimal storage

## Next Steps

### 🎯 Future Enhancements

1. **Transcription:**
   - Integrate AWS Transcribe
   - Convert recording to text
   - Store transcripts in S3

2. **RAG System:**
   - Create embeddings from transcripts
   - Store in vector database (Pinecone/Weaviate)
   - Chat interface to query meeting notes

3. **Recording Management:**
   - List all recordings on dashboard
   - Download/delete recordings
   - Share recordings with participants

4. **Advanced Features:**
   - Live transcription during meetings
   - AI-generated meeting summaries
   - Action items extraction
   - Speaker identification

## Security Best Practices

1. **Never hardcode credentials** - Always use `.env`
2. **Use private S3 buckets** - Generate presigned URLs for access
3. **Rotate AWS keys regularly** - Use IAM best practices
4. **Enable S3 encryption** - Encrypt at rest
5. **Set S3 lifecycle policies** - Auto-delete old recordings
6. **Use HTTPS only** - Ensure secure transmission

## Support

- Agora Documentation: https://docs.agora.io/en/cloud-recording/
- AWS S3 Documentation: https://docs.aws.amazon.com/s3/
- Django Documentation: https://docs.djangoproject.com/

## Questions?

If you encounter issues:
1. Check the browser console for JavaScript errors
2. Check Django server logs for backend errors
3. Check Agora Console logs for recording status
4. Verify all environment variables are set correctly
