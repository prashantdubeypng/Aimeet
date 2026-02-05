# AIMeet - Requirements Document

## 1. Functional Requirements

### 1.1 User Management
- FR-1.1: Users must be able to register with username, email, and password
- FR-1.2: Users must be able to log in with credentials
- FR-1.3: Users must be able to log out
- FR-1.4: Users must be able to reset password via email
- FR-1.5: User profiles must store name, email, profile picture

### 1.2 Meeting Management
- FR-2.1: Users can create a meeting with title, description, and max participants
- FR-2.2: System generates unique shareable room code for each meeting
- FR-2.3: Users can join meetings using room code
- FR-2.4: Meeting host can end the meeting
- FR-2.5: Meeting state tracks: active, ended, archived
- FR-2.6: Users can view list of their meetings (hosted and joined)
- FR-2.7: Users can delete or archive completed meetings

### 1.3 Real-Time Video & Audio
- FR-3.1: Video streaming using Agora RTC SDK
- FR-3.2: Audio streaming with VP8 codec
- FR-3.3: Dynamic bitrate adjustment based on network
- FR-3.4: Participants can mute/unmute audio and video
- FR-3.5: Host can kick participants
- FR-3.6: Screen sharing capability (optional, future)

### 1.4 Recording
- FR-4.1: Audio is automatically recorded during meeting using MediaRecorder
- FR-4.2: Recording saved as WebM format locally
- FR-4.3: Users can upload recording after meeting
- FR-4.4: Recording uploaded to AWS S3
- FR-4.5: System stores recording metadata (size, duration, upload time)
- FR-4.6: Presigned URLs generated for private S3 access

### 1.5 Transcription
- FR-5.1: Uploaded recordings sent to AssemblyAI for transcription
- FR-5.2: System polls AssemblyAI for transcription status
- FR-5.3: Completed transcripts saved to database
- FR-5.4: Transcript status tracked: not_started, processing, completed, failed
- FR-5.5: Transcript linked to meeting record

### 1.6 Knowledge Processing (RAG)
- FR-6.1: Users can trigger "Prepare for Search" to process transcript
- FR-6.2: System chunks transcript using recursive character splitting (500 tokens, 50 overlap)
- FR-6.3: Chunks stored in TranscriptChunk model
- FR-6.4: Chunks embedded using OpenAI text-embedding-3-small
- FR-6.5: Embeddings stored in Qdrant vector database
- FR-6.6: Idempotent processing: check timestamps to avoid reprocessing

### 1.7 Question Answering (RAG Query)
- FR-7.1: Users can ask questions about meeting content
- FR-7.2: Question embedded using same OpenAI model
- FR-7.3: System searches Qdrant for top-5 similar chunks
- FR-7.4: Conversation history retrieved for context
- FR-7.5: GPT-4o called with context + history + question
- FR-7.6: Response generated and displayed to user
- FR-7.7: Q&A turn saved to ConversationHistory

### 1.8 Meeting Preparation (Sticky Notes)
- FR-8.1: When creating new meeting, system suggests related past meetings
- FR-8.2: Suggestions based on meeting title/agenda keywords
- FR-8.3: Shows what was discussed about same topics before
- FR-8.4: Users can expand sticky notes to see full context
- FR-8.5: Helps prevent duplicate discussions

### 1.9 Document Management
- FR-9.1: Users can upload documents (PDF, DOCX, TXT)
- FR-9.2: Documents stored in S3
- FR-9.3: Document text extracted and stored
- FR-9.4: Documents chunked same way as transcripts
- FR-9.5: Document chunks embedded and stored in Qdrant
- FR-9.6: Users can view list of documents per meeting
- FR-9.7: Users can delete documents

### 1.10 Unified Search
- FR-10.1: Questions search both transcripts and documents
- FR-10.2: Results include source type (meeting transcript vs document)
- FR-10.3: Search results show relevance scores
- FR-10.4: Source metadata (timestamps, document names) included

### 1.11 Chat
- FR-11.1: Real-time chat during meetings using WebSocket
- FR-11.2: Chat messages saved to database
- FR-11.3: Users can view chat history
- FR-11.4: Message timestamps tracked
- FR-11.5: Messages linked to user and meeting

### 1.12 Reporting & Analytics (Future)
- FR-12.1: Meeting duration and participant count
- FR-12.2: Transcript statistics (word count, duration)
- FR-12.3: Q&A usage statistics
- FR-12.4: Most discussed topics across meetings

---

## 2. Non-Functional Requirements

### 2.1 Performance
- NFR-1.1: Q&A response time: <4 seconds (including LLM latency)
- NFR-1.2: Vector search latency: <500ms
- NFR-1.3: API response time: <1 second for non-AI endpoints
- NFR-1.4: Page load time: <3 seconds
- NFR-1.5: Concurrent users: 100+ with auto-scaling
- NFR-1.6: Transcript processing: <1 minute for typical meeting

### 2.2 Scalability
- NFR-2.1: Horizontal scaling via EC2 Auto Scaling Groups
- NFR-2.2: Database: RDS with read replicas
- NFR-2.3: S3 handles unlimited storage
- NFR-2.4: Qdrant Cloud manages vector scaling
- NFR-2.5: Support growth from 10 to 10,000 users

### 2.3 Reliability
- NFR-3.1: 99.5% uptime SLA
- NFR-3.2: Automated daily database backups
- NFR-3.3: Multi-AZ RDS for failover
- NFR-3.4: CloudFront CDN for static assets
- NFR-3.5: Graceful error handling and user feedback

### 2.4 Security
- NFR-4.1: HTTPS for all communications
- NFR-4.2: Password hashing with bcrypt
- NFR-4.3: JWT tokens for API authentication
- NFR-4.4: SQL injection protection via ORM
- NFR-4.5: XSS protection via template escaping
- NFR-4.6: CSRF protection on forms
- NFR-4.7: S3 encryption at rest (AES-256)
- NFR-4.8: Database encryption (KMS)
- NFR-4.9: API keys in Secrets Manager (no hardcoding)
- NFR-4.10: Private S3 access via presigned URLs
- NFR-4.11: Private subnet for RDS (no public IP)
- NFR-4.12: Rate limiting: 100 requests/minute per user

### 2.5 Usability
- NFR-5.1: Responsive design for mobile (375px+) and desktop
- NFR-5.2: Accessibility: WCAG 2.1 Level AA compliance
- NFR-5.3: Intuitive UI with clear navigation
- NFR-5.4: Error messages explain what went wrong
- NFR-5.5: Dark and light mode support (future)

### 2.6 Maintainability
- NFR-6.1: Code documented with docstrings
- NFR-6.2: DRY principle: no code duplication
- NFR-6.3: Clear separation of concerns
- NFR-6.4: Comprehensive logging with timestamps
- NFR-6.5: Automated testing (unit + integration)

### 2.7 Compatibility
- NFR-7.1: Browser support: Chrome, Firefox, Safari, Edge (latest 2 versions)
- NFR-7.2: Mobile support: iOS Safari, Android Chrome
- NFR-7.3: Python 3.13+ support
- NFR-7.4: PostgreSQL 12+ support

---

## 3. System Requirements

### 3.1 Software Requirements
- **Backend**: Django 4.x, Python 3.13+
- **Database**: PostgreSQL 12+ (or SQLite for dev)
- **Web Server**: Gunicorn + Nginx
- **Vector DB**: Qdrant 1.x
- **Message Queue** (future): Celery + Redis

### 3.2 Hardware Requirements (Production)
- **Compute**: EC2 t3.medium (2 vCPU, 4GB RAM) minimum
  - Development: t3.small sufficient
  - Production: t3.large+ with auto-scaling 2-10 instances
- **Database**: RDS t4g.medium (2 vCPU, 1GB RAM)
  - Storage: 100GB gp3 (auto-scaling)
- **Bandwidth**: 10 Mbps minimum (up to 1 Gbps for scaling)

### 3.3 Browser Requirements
- Minimum: Chrome 90+, Firefox 88+, Safari 14+, Edge 90+
- WebRTC support required for video
- LocalStorage and SessionStorage support
- WebSocket support

---

## 4. Dependencies

### 4.1 Backend Dependencies
```
Django==4.2
djangorestframework==3.14.0
psycopg2-binary==2.9.0
python-dotenv==1.0.0

# AI & ML
openai==2.16.0
qdrant-client==1.16.2
requests==2.31.0

# Transcription
AssemblyAI (API, no package)

# Cloud
boto3==1.26.137

# Real-time
pusher==3.3.1

# Video
agora-rtm (Agora SDK)
agora-token-builder (Token generation)

# Utilities
python-dateutil==2.8.2
pytz==2023.3
Pillow==10.0.0
```

### 4.2 Frontend Dependencies
```
Agora RTC SDK v4.24.2 (JavaScript)
Bootstrap 5.3
jQuery 3.6 (optional, for DOM manipulation)
```

### 4.3 External Services
- **OpenAI API**: Embeddings (text-embedding-3-small) + LLM (GPT-4o)
- **AssemblyAI API**: Speech-to-text transcription
- **Qdrant Cloud**: Vector database hosting
- **AWS Services**: EC2, RDS, S3, CloudWatch, Secrets Manager, ALB
- **Agora**: Video/audio RTC
- **Pusher**: WebSocket for chat

---

## 5. API Requirements

### 5.1 REST API Specifications
- **Base URL**: `/api/` or `/` (depending on endpoint)
- **Content-Type**: `application/json`
- **Authentication**: Django session + optional JWT for API clients
- **Response Format**: JSON with status, data, and error fields
- **Pagination**: Limit + offset for list endpoints
- **Versioning**: Not required initially (v1 implicit)

### 5.2 WebSocket Requirements
- **Protocol**: WebSocket (Pusher-managed)
- **Channels**: Per-meeting chat channels
- **Message Format**: JSON
- **Auto-reconnect**: Client-side retry logic

### 5.3 Rate Limiting
- 100 requests/minute per user
- 1000 requests/minute per IP
- Q&A queries: 10 per minute per user

---

## 6. Infrastructure Requirements

### 6.1 AWS Services Required
- **Compute**: EC2 (application server)
- **Database**: RDS PostgreSQL (relational data)
- **Storage**: S3 (recordings, documents)
- **CDN**: CloudFront (static assets, S3 downloads)
- **Load Balancer**: Application Load Balancer (ALB)
- **Monitoring**: CloudWatch (logs, metrics, alarms)
- **Secrets**: Secrets Manager (API keys, credentials)
- **Networking**: VPC, Security Groups, NAT Gateway

### 6.2 Third-Party Services Required
- **Qdrant Cloud**: Vector database (managed)
- **OpenAI**: API access (embeddings + GPT-4o)
- **AssemblyAI**: Transcription API
- **Agora**: RTC infrastructure
- **Pusher**: WebSocket infrastructure

### 6.3 Monitoring & Logging
- CloudWatch Logs: All application logs
- CloudWatch Metrics: CPU, memory, request latency
- CloudWatch Alarms: Errors, latency spikes, service degradation
- Application Insights: APM for performance tracking (optional)

---

## 7. Data Requirements

### 7.1 Database Schema
- **Users**: id, username, email, password_hash, created_at
- **MeetingRoom**: id, room_code, host_id, title, description, status, recording data, transcript data, embedding metadata
- **TranscriptChunk**: id, meeting_id, chunk_text, chunk_index, embedding_vector_id
- **DocumentUpload**: id, meeting_id, file_name, file_type, s3_url, raw_text
- **DocumentChunk**: id, document_id, chunk_text, chunk_index, embedding_vector_id
- **ConversationHistory**: id, meeting_id, user_id, user_question, assistant_response, relevant_chunks
- **ChatMessage**: id, user_id, content, created_at

### 7.2 Vector Database Schema
- **Collection**: meeting_transcripts
  - Dimension: 1536 (OpenAI text-embedding-3-small)
  - Distance: Cosine Similarity
  - Payload: meeting_id, chunk_index, text, timestamps

### 7.3 Storage (S3) Structure
```
s3://aimeet-s3-bucket/
├── recordings/
│   ├── meeting_123_audio.webm
│   └── meeting_124_audio.webm
├── documents/
│   ├── document_456.pdf
│   └── document_457.txt
└── transcripts/
    ├── transcript_123.txt
    └── transcript_124.txt
```

### 7.4 Data Retention Policy
- Recordings: Keep indefinitely (archive to Glacier after 90 days)
- Transcripts: Keep indefinitely
- Chat messages: Keep indefinitely
- Documents: Keep indefinitely
- Database backups: 35-day retention
- Logs: 30-day retention

---

## 8. Integration Requirements

### 8.1 External API Integrations
- **OpenAI API**: Embeddings (batch and single)
- **AssemblyAI API**: Transcription (async polling)
- **Qdrant API**: Vector search and storage
- **AWS SDK (Boto3)**: S3 operations
- **Agora SDK**: Token generation and RTC
- **Pusher API**: WebSocket messaging

### 8.2 Authentication Integrations
- Django authentication (built-in)
- Optional: OAuth2 (Google, GitHub) - future
- Optional: SAML - future

---

## 9. Testing Requirements

### 9.1 Unit Testing
- Models: Test data validation and relationships
- Views: Test API endpoints with mocks
- Utilities: Test embedding, chunking, RAG functions
- Target: >80% code coverage

### 9.2 Integration Testing
- End-to-end meeting flow
- Recording upload and transcription
- RAG pipeline (chunk → embed → search → query)
- Document upload and search

### 9.3 Performance Testing
- Load test: 100 concurrent users
- Transcription processing time
- Q&A response latency
- Vector search speed

### 9.4 Security Testing
- OWASP Top 10 vulnerability scanning
- SQL injection attempts
- XSS payloads
- CSRF validation

---

## 10. Documentation Requirements

### 10.1 Code Documentation
- Docstrings for all functions/methods
- Inline comments for complex logic
- README.md for setup and usage
- API documentation (Swagger/OpenAPI)

### 10.2 User Documentation
- Quick start guide
- Feature tutorials
- FAQ
- Troubleshooting guide

### 10.3 System Documentation
- ARCHITECTURE.md (system design)
- DESIGN.md (diagrams and flows)
- REQUIREMENTS.md (this document)
- Deployment guide

---

## 11. Future Enhancements

### 11.1 Planned Features
- Speaker diarization (identify who said what)
- Automatic action item detection
- Topic summaries and key moments
- Calendar integration
- Role-based access control
- Multi-language support
- Slack/Teams integration
- Custom embedding models

### 11.2 Optimization Opportunities
- Redis caching layer (conversation history, user sessions)
- Celery background jobs (transcription polling, document processing)
- WebRTC data channels (peer-to-peer communication)
- Progressive Web App (PWA) capabilities

---

## 12. Success Criteria

### 12.1 Functional Success
- All FR requirements fully implemented
- All tests passing
- No critical bugs in production

### 12.2 Performance Success
- Page load time <3 seconds (95th percentile)
- Q&A response time <4 seconds (95th percentile)
- 99.5% uptime maintained
- <1 second vector search latency

### 12.3 User Success
- User registration completion rate >90%
- Meeting creation to Q&A within 5 minutes
- >80% of users try Q&A feature within first week

### 12.4 Business Success
- Support 1000+ concurrent users
- Cost <$1000/month at 1000-user scale
- Document uploaded for >50% of meetings
- Sticky notes used in >40% of meetings

---

## 13. Constraints & Assumptions

### 13.1 Constraints
- OpenAI API rate limits (depends on plan)
- AssemblyAI transcription queue
- AWS service quotas
- Budget limitations for cloud services

### 13.2 Assumptions
- Users have stable internet connection (>2 Mbps)
- Meetings typically 30 minutes to 2 hours
- Transcripts typically 5K-20K tokens
- Users have modern browsers (2020+)
- Organizations want to keep data private (not shared)

---

## 14. Compliance & Standards

### 14.1 Security Standards
- SSL/TLS 1.3 for encryption
- OWASP Top 10 compliance
- GDPR compliance (user data protection)
- HIPAA compliance (if health data involved) - future

### 14.2 Coding Standards
- PEP 8 for Python code style
- Django best practices
- RESTful API design
- Semantic versioning for releases

### 14.3 Accessibility Standards
- WCAG 2.1 Level AA compliance
- Keyboard navigation support
- Screen reader compatibility
- Color contrast ratios >4.5:1
