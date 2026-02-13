# AIMeet

![CI](https://github.com/prashantdubeypng/Aimeet/workflows/CI%20-%20Tests%20and%20Checks/badge.svg)
![Deploy](https://github.com/prashantdubeypng/Aimeet/workflows/CD%20-%20Deploy%20to%20Render/badge.svg)
![Security](https://github.com/prashantdubeypng/Aimeet/workflows/Weekly%20Security%20Scan/badge.svg)

AIMeet is an AI-powered meeting intelligence platform that captures, transcribes, and makes meeting knowledge instantly searchable. Unlike basic transcription tools, AIMeet understands context. It remembers what you discussed before, connects related past meetings to current agendas, and answers follow-up questions with full conversation history.

This project is built with Django and integrates real-time video, cloud storage, transcription, vector search, and modern AI for intelligent meeting memory.

## Core Features

**Meeting Capture**
- Real-time video and audio meetings using Agora SDK
- Automatic audio recording during meetings
- Secure storage in Amazon S3
- Real-time chat with conversation history

**Intelligent Transcription**
- Automatic speech-to-text via AssemblyAI
- Transcript saved and indexed for search
- Time-stamped chunks for easy reference

**Contextual Q&A**
- Ask questions about what was discussed
- AI remembers your past questions for better answers
- Retrieves relevant transcript sections in seconds
- Powered by OpenAI embeddings and GPT-4o

**Meeting Preparation (Sticky Notes)**
- When creating a new meeting with an agenda, AIMeet automatically shows related past meetings
- See what you discussed about hiring, features, decisions before
- Prevents duplicate discussions and ensures consistency
- Helps you prepare with full context from history

**Document Intelligence**
- Upload external documents (PDFs, Word docs, text files)
- Ask questions across both meeting transcripts and uploaded documents
- Single interface to query all your organizational knowledge
- Documents indexed the same way as transcripts for unified search

**Conversation Memory**
- Each Q&A turn is saved and linked to relevant transcript sections
- Follow-up questions include context from previous exchanges
- Team stays aligned across multiple meetings

## How AIMeet Works

**Step 1: Capture**
- Start a meeting and participants join via room code
- Audio records automatically during the meeting
- Chat messages are saved in real-time

**Step 2: Process**
- After meeting ends, recording uploads to S3
- AssemblyAI transcribes the audio (handles long recordings)
- System splits transcript into searchable chunks
- OpenAI converts chunks to embedding vectors (1536 dimensions)
- Qdrant vector database stores all vectors for fast retrieval

**Step 3: Prepare**
- Users optionally upload documents (PDFs, research, specs)
- Documents are extracted and embedded the same way
- Everything is indexed in Qdrant for unified search

**Step 4: Use**
- When joining a new meeting, AIMeet suggests related past discussions (sticky notes)
- Users can ask questions about what was discussed
- AI searches all transcripts and documents, retrieves top matches
- GPT-4o generates answers with full conversation history context
- Team gets intelligent answers instead of manual searching

## Tech stack

**Backend & Infrastructure**
- Django 4.x with Python 3.13
- PostgreSQL for persistent data
- AWS S3 for recordings and documents

- Powered by HuggingFace embeddings and Ollama LLM
- Agora RTC SDK v4.24.2 for video/audio
**Meeting Agenda (Sticky Notes)**
- Left-side agenda panel auto-generates discussion points from past transcripts and documents
- Points are grounded in your stored data only
- Add or remove points to customize the agenda
- Helps you prepare with context from meeting history
- OpenAI GPT-4o for intelligent responses
- AssemblyAI for speech-to-text transcription
- Qdrant Cloud for vector database

**Architecture Details**
See [ARCHITECTURE.md](ARCHITECTURE.md) for comprehensive system design, AWS deployment topology, and scaling strategies.

## Local setup

### Prerequisites
- Python 3.13+
- PostgreSQL 12+ (or SQLite for development)
- Git

### Installation

1. Clone the repository
   ```bash
   git clone https://github.com/prashantdubeypng/Aimeet.git
   cd Aimeet
   ```

2. Create virtual environment
   ```bash
   python -m venv env
   ```

3. Activate environment
   - Windows: `env\Scripts\activate`
   - macOS/Linux: `source env/bin/activate`

4. Install dependencies
   ```bash
   pip install -r requirements.txt
   ```

5. Configure environment variables
   - Copy `.env.example` to `videocaller/.env`
   - Add your API keys (see Environment Variables section below)

6. Run migrations
   ```bash
   cd videocaller
   python manage.py makemigrations
   python manage.py migrate
   ```

7. Create superuser (optional, for admin panel)
   ```bash
   python manage.py createsuperuser
   ```

8. Start development server
   ```bash
   python manage.py runserver
   ```
   - Open `http://localhost:8000` in browser

## Environment variables

Create `videocaller/.env` with the following:

```
# Agora (Video SDK)
AGORA_APP_ID=your_agora_app_id
AGORA_APP_CERTIFICATE=your_agora_app_certificate

# AWS S3 (Storage)
AWS_ACCESS_KEY_ID=your_aws_key
AWS_SECRET_ACCESS_KEY=your_aws_secret
AWS_STORAGE_BUCKET_NAME=aimeet-s3-bucket
AWS_S3_REGION_NAME=ap-south-1

# AssemblyAI (Transcription)
ASSEMBLYAI_API_KEY=your_assemblyai_key

# OpenAI (Embeddings + LLM)
OPENAI_API_KEY=your_openai_key
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_EMBEDDING_DIMENSION=1536
OPENAI_LLM_MODEL=gpt-4o-mini
OPENAI_MAX_TOKENS=1000

# Qdrant (Vector Database)
QDRANT_URL=https://your-qdrant-cloud-url:6333
QDRANT_API_KEY=your_qdrant_api_key
QDRANT_COLLECTION_NAME=meeting_transcripts

# Pusher (Real-time Chat)
PUSHER_APP_ID=your_pusher_app_id
PUSHER_KEY=your_pusher_key
PUSHER_SECRET=your_pusher_secret
PUSHER_CLUSTER=your_pusher_cluster
```

## Usage

### Basic Flow

1. **Register and Login**
   - Create account on registration page
   - Login with credentials

2. **Create Meeting**
   - Click "Create Meeting"
   - Add title and description
   - Get shareable room code

3. **Join Meeting**
   - Share room code with participants
   - Participants join and video/audio streams start
   - Chat available during meeting

4. **Record and Upload**
   - Recording happens automatically during meeting
   - After meeting ends, upload button appears
   - Recording uploads to S3

5. **Process for Search**
   - Wait for transcription to complete
   - Click "Prepare for Search" to chunk and embed
   - Status shows when ready

6. **View Meeting Preparation**
   - When creating a new meeting with similar agenda
   - See sticky notes of related past discussions
   - Review what was discussed before

7. **Ask Questions**
   - In meeting details, type your question
   - AI searches all transcripts and documents
   - Get answer with relevant sections and conversation history

8. **Upload Documents**
   - Upload PDFs, Word docs, or text files
   - Ask questions across transcripts + documents
   - Unified knowledge search

## API Endpoints

### Meeting Management
```
GET    /                           - List meetings
POST   /create/                    - Create meeting
GET    /meeting/<code>/            - Join meeting
POST   /meeting/<code>/end/        - End meeting
```

### Recording
```
POST   /meeting/<code>/upload-recording/     - Upload audio
GET    /meeting/<code>/query-recording/      - Check status
```

### RAG & Questions
```
GET    /api/meetings/<id>/prepare-rag/       - Prepare transcript for search
POST   /api/meetings/<id>/query/             - Ask question
GET    /api/meetings/<id>/conversation-history/ - Get Q&A history

POST   /api/meetings/<id>/upload-document/   - Upload document
GET    /api/meetings/<id>/documents/         - List documents
```

### Chat
```
GET    /chat/messages/             - Get message history
POST   /chat/messages/             - Send message
```

### Video
```
POST   /token/                     - Get Agora video token
```

## Deployment

### Local Development
```bash
python manage.py runserver
# App runs on http://localhost:8000
# Qdrant on http://localhost:6333 (if local)
```

### Production on AWS

**Recommended Setup:**
- Django: EC2 with Auto Scaling or ECS Fargate
- Database: RDS PostgreSQL Multi-AZ
- Storage: S3 with CloudFront CDN
- Vector DB: Qdrant Cloud
- Monitoring: CloudWatch + Alarms

**Deployment Steps:**
1. Create RDS PostgreSQL instance
2. Create S3 bucket with appropriate policies
3. Deploy Django app to EC2/ECS
4. Configure environment variables in AWS Secrets Manager
5. Set up Qdrant Cloud and get API key
6. Run migrations on deployed database
7. Configure ALB and auto-scaling
8. Enable CloudWatch monitoring and alarms

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed AWS deployment topology and cost estimation.

## Features Roadmap

### Current
- Real-time video meetings
- Automatic transcription
- Contextual Q&A with conversation memory
- Meeting preparation with sticky notes
- Document upload and unified search

### Planned
- Speaker diarization (identify who said what)
- Automatic action item detection
- Topic summaries and highlights
- Calendar integration with meeting reminders
- Role-based access control
- Multi-language transcription
- Meeting highlights and key moments
- Integration with Slack and Teams
- Custom embedding models for privacy
- On-premise Qdrant deployment option

## Architecture

This project uses a distributed architecture:
- **Client**: HTML/CSS/JS with Agora SDK
- **API**: Django REST + WebSockets
- **Processing**: Chunking, embedding, vector search
- **Storage**: PostgreSQL + S3 + Qdrant
- **AI**: OpenAI APIs for embeddings and LLM responses

For detailed architecture, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Performance & Scalability

- Handles 100+ concurrent users with auto-scaling
- Transcripts processed within minutes
- Q&A responses generated in 2-4 seconds
- Vector search completes in <500ms
- Monthly cost scales from $350 (startup) to $1000+ (scale)

## Contributing

We welcome contributions. Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes with clear commit messages
4. Submit a pull request with description

For larger changes, open an issue first to discuss.

## License

MIT License. See the LICENSE file for details.

## Support

For issues, questions, or feature requests, please open a GitHub issue.
