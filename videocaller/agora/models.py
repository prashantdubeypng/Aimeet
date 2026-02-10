from django.db import models
from django.contrib.auth.models import User
import uuid

class MeetingRoom(models.Model):
    room_id = models.CharField(max_length=100, unique=True, default=uuid.uuid4)
    room_code = models.CharField(max_length=10, unique=True)  # Shareable code like "abc-def-ghi"
    host = models.ForeignKey(User, on_delete=models.CASCADE, related_name='hosted_meetings')
    title = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    max_participants = models.IntegerField(default=10)
    
    def __str__(self):
        return f"{self.title} - {self.room_code}"
    
    class Meta:
        ordering = ['-created_at']

    def get_recording(self):
        try:
            return self.recording
        except MeetingRecording.DoesNotExist:
            return MeetingRecording.objects.create(meeting=self)

    def get_transcript(self):
        try:
            return self.transcript
        except MeetingTranscript.DoesNotExist:
            return MeetingTranscript.objects.create(meeting=self)

    def get_rag_state(self):
        try:
            return self.rag_state
        except MeetingRagState.DoesNotExist:
            return MeetingRagState.objects.create(meeting=self)


class MeetingRecording(models.Model):
    meeting = models.OneToOneField(MeetingRoom, on_delete=models.CASCADE, related_name='recording')
    recording_enabled = models.BooleanField(default=False)
    recording_sid = models.CharField(max_length=255, null=True, blank=True, help_text="Agora Recording SID")
    recording_resource_id = models.CharField(max_length=255, null=True, blank=True, help_text="Agora Resource ID")
    recording_uid = models.IntegerField(null=True, blank=True, help_text="Agora Recording Bot UID")
    recording_status = models.CharField(
        max_length=50,
        default='not_started',
        choices=[('not_started', 'Not Started'), ('recording', 'Recording'), ('completed', 'Completed'), ('failed', 'Failed')]
    )
    s3_recording_url = models.URLField(max_length=500, null=True, blank=True, help_text="S3 URL for recording")
    recording_duration = models.IntegerField(default=0, help_text="Duration in seconds")

    def __str__(self):
        return f"Recording - {self.meeting.title}"


class MeetingTranscript(models.Model):
    meeting = models.OneToOneField(MeetingRoom, on_delete=models.CASCADE, related_name='transcript')
    transcript_text = models.TextField(null=True, blank=True)
    transcript_status = models.CharField(
        max_length=50,
        default='not_started',
        choices=[('not_started', 'Not Started'), ('processing', 'Processing'), ('completed', 'Completed'), ('failed', 'Failed')]
    )
    transcript_id = models.CharField(max_length=255, null=True, blank=True, help_text="AssemblyAI Transcript ID")
    s3_transcript_url = models.URLField(max_length=500, null=True, blank=True, help_text="S3 URL for transcript")

    def __str__(self):
        return f"Transcript - {self.meeting.title}"


class MeetingRagState(models.Model):
    meeting = models.OneToOneField(MeetingRoom, on_delete=models.CASCADE, related_name='rag_state')
    chunks_created_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp when chunks were created")
    embeddings_created_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp when embeddings were generated")
    embedding_version = models.IntegerField(default=1, help_text="Version of embeddings (for migration)")

    def __str__(self):
        return f"RAG State - {self.meeting.title}"


class ChatMessage(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_messages')
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username}: {self.content[:30]}"

    class Meta:
        ordering = ['-created_at']


class TranscriptChunk(models.Model):
    """Store transcript chunks with their embeddings for RAG"""
    meeting = models.ForeignKey(MeetingRoom, on_delete=models.CASCADE, related_name='transcript_chunks')
    chunk_text = models.TextField(help_text="Text chunk from transcript")
    chunk_index = models.IntegerField(help_text="Order of chunk in transcript")
    start_time = models.IntegerField(null=True, blank=True, help_text="Start time in seconds")
    end_time = models.IntegerField(null=True, blank=True, help_text="End time in seconds")
    embedding_vector_id = models.CharField(max_length=255, null=True, blank=True, help_text="Vector DB ID")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Chunk {self.chunk_index} - {self.meeting.title}"

    class Meta:
        ordering = ['meeting', 'chunk_index']


class DocumentUpload(models.Model):
    """Store uploaded external documents/audio linked to a meeting"""
    meeting = models.ForeignKey(MeetingRoom, on_delete=models.CASCADE, related_name='document_uploads')
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='document_uploads')
    file_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=50, help_text="File extension or MIME hint")
    storage_path = models.CharField(max_length=500, help_text="Storage path for local processing")
    s3_url = models.URLField(max_length=500, null=True, blank=True)
    raw_text = models.TextField(null=True, blank=True)
    status = models.CharField(
        max_length=50,
        default='uploaded',
        choices=[
            ('uploaded', 'Uploaded'),
            ('processing', 'Processing'),
            ('completed', 'Completed'),
            ('failed', 'Failed')
        ]
    )
    error_message = models.TextField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    embeddings_created_at = models.DateTimeField(null=True, blank=True)
    embedding_version = models.IntegerField(default=1, help_text="Version of embeddings (for migration)")
    chunk_count = models.IntegerField(default=0, help_text="Number of chunks created")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.file_name} - {self.meeting.title}"

    class Meta:
        ordering = ['-created_at']


class DocumentChunk(models.Model):
    """Store document chunks with embeddings for RAG"""
    document = models.ForeignKey(DocumentUpload, on_delete=models.CASCADE, related_name='chunks')
    chunk_text = models.TextField(help_text="Text chunk from document")
    chunk_index = models.IntegerField(help_text="Order of chunk in document")
    block_type = models.CharField(max_length=50, default='text', help_text="text/table/image/other")
    metadata = models.JSONField(default=dict, help_text="Extractor metadata")
    embedding_vector_id = models.CharField(max_length=255, null=True, blank=True, help_text="Vector DB ID")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"DocChunk {self.chunk_index} - {self.document.file_name}"

    class Meta:
        ordering = ['document', 'chunk_index']


class MeetingAgendaPoint(models.Model):
    """Shared agenda points for a meeting."""
    meeting = models.ForeignKey(MeetingRoom, on_delete=models.CASCADE, related_name='agenda_points')
    text = models.TextField()
    order = models.IntegerField(default=0)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    is_ai_generated = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Agenda {self.order} - {self.meeting.title}"

    class Meta:
        ordering = ['order', 'created_at']


class ConversationHistory(models.Model):
    """Store Q&A history for context-aware responses"""
    meeting = models.ForeignKey(MeetingRoom, on_delete=models.CASCADE, related_name='conversation_history')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    user_question = models.TextField()
    assistant_response = models.TextField()
    relevant_chunks = models.JSONField(default=list, help_text="List of chunk IDs used for response")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.meeting.title} - {self.user.username}"

    class Meta:
        ordering = ['-created_at']
