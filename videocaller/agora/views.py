import os
import time
import json
import random
import string
import logging
import requests

from django.http.response import JsonResponse
from django.http import StreamingHttpResponse, HttpResponseNotAllowed
from django.contrib.auth import get_user_model, authenticate, login
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST, require_http_methods
from django.contrib.auth.forms import UserCreationForm
from django.db.models import Q
from django.db import models
from django.core.files.base import ContentFile
from django.conf import settings

from .agora_key.RtcTokenBuilder import RtcTokenBuilder, Role_Attendee
from .models import MeetingRoom, ChatMessage, DocumentUpload, DocumentChunk, MeetingAgendaPoint
from .recording_utils import AgoraCloudRecording, S3Manager
from .assemblyai_utils import AssemblyAIClient
from .rag_utils import generate_rag_response, process_transcript_for_rag, stream_rag_response_async
from .agenda_utils import generate_agenda_points
from asgiref.sync import sync_to_async
from django_q.tasks import async_task
from pusher import Pusher

logger = logging.getLogger(__name__)

# Lazy-load Pusher client to avoid crashes when env vars aren't set (e.g., in CI)
_pusher_client = None

def get_pusher_client():
    global _pusher_client
    if _pusher_client is None:
        app_id = os.environ.get('PUSHER_APP_ID')
        key = os.environ.get('PUSHER_KEY')
        secret = os.environ.get('PUSHER_SECRET')
        cluster = os.environ.get('PUSHER_CLUSTER')
        
        # Only initialize if all required env vars are present
        if all([app_id, key, secret, cluster]):
            _pusher_client = Pusher(
                app_id=app_id,
                key=key,
                secret=secret,
                ssl=True,
                cluster=cluster
            )
    return _pusher_client


def generate_room_code():
    """Generate a unique 8-character room code like abc-d-ghi"""
    chars = string.ascii_lowercase + string.digits
    code = '-'.join([''.join(random.choices(chars, k=3)), random.choice(chars), ''.join(random.choices(chars, k=3))])
    return code


# User Registration
def register(request):
    if request.user.is_authenticated:
        return redirect('home')
    
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password1')
            user = authenticate(username=username, password=password)
            login(request, user)
            return redirect('home')
    else:
        form = UserCreationForm()
    
    return render(request, 'agora/register.html', {'form': form})


# Home Page - List Meeting Rooms
@login_required(login_url='/register/')
def home(request):
    # Get all active rooms
    all_rooms = MeetingRoom.objects.filter(is_active=True)
    user_rooms = request.user.hosted_meetings.filter(is_active=True)

    # Recent chat messages for dashboard
    chat_messages = ChatMessage.objects.select_related('user').order_by('-created_at')[:50]
    
    return render(request, 'agora/home.html', {
        'all_rooms': all_rooms,
        'user_rooms': user_rooms,
        'chat_messages': list(reversed(chat_messages))
    })


# Create Meeting Room
@login_required(login_url='/register/')
def create_room(request):
    if request.method == 'POST':
        title = request.POST.get('title', 'Untitled Meeting')
        description = request.POST.get('description', '')
        
        # Generate unique room code
        room_code = generate_room_code()
        
        room = MeetingRoom.objects.create(
            host=request.user,
            title=title,
            description=description,
            room_code=room_code
        )
        
        return redirect('meeting', room_code=room.room_code)
    
    return render(request, 'agora/create_room.html')


# Join Meeting Room by Code
@login_required(login_url='/register/')
def join_room(request):
    if request.method == 'POST':
        room_code = request.POST.get('room_code', '').strip()
        
        try:
            room = MeetingRoom.objects.get(room_code=room_code, is_active=True)
            return redirect('meeting', room_code=room.room_code)
        except MeetingRoom.DoesNotExist:
            return render(request, 'agora/join_room.html', {'error': 'Room not found or inactive'})
    
    return render(request, 'agora/join_room.html')


# Meeting Room Interface
@login_required(login_url='/register/')
def meeting(request, room_code):
    room = get_object_or_404(MeetingRoom, room_code=room_code, is_active=True)
    
    return render(request, 'agora/meeting.html', {
        'room': room,
        'room_code': room_code,
        'room_id': str(room.room_id),
        'is_host': room.host == request.user,
        'meeting_db_id': room.id
    })


# End Meeting (Host Only)
@login_required(login_url='/register/')
@require_POST
def end_meeting(request, room_code):
    room = get_object_or_404(MeetingRoom, room_code=room_code)
    
    if room.host != request.user:
        return JsonResponse({'error': 'Only host can end meeting'}, status=403)
    
    room.is_active = False
    room.save()
    
    return JsonResponse({'message': 'Meeting ended'})


# Pusher Authentication
def pusher_auth(request):
    client = get_pusher_client()
    if not client:
        return JsonResponse({'error': 'Pusher not configured'}, status=503)
    
    payload = client.authenticate(
        channel=request.POST['channel_name'],
        socket_id=request.POST['socket_id'],
        custom_data={
            'user_id': request.user.id,
            'user_info': {
                'id': request.user.id,
                'name': request.user.username
            }
        })
    return JsonResponse(payload)


# Generate Agora Token for Room
def generate_agora_token(request):
    appID = settings.AGORA_APP_ID
    appCertificate = settings.AGORA_APP_CERTIFICATE
    
    data = json.loads(request.body.decode('utf-8'))
    channelName = data['channelName']
    
    # For Agora SDK v4, use numeric UID
    uid = request.user.id
    
    expireTimeInSeconds = 3600
    currentTimestamp = int(time.time())
    privilegeExpiredTs = currentTimestamp + expireTimeInSeconds

    token = RtcTokenBuilder.buildTokenWithAccount(
        appID, appCertificate, channelName, str(uid), Role_Attendee, privilegeExpiredTs)

    return JsonResponse({'token': token, 'appID': appID, 'uid': uid})


# Start Cloud Recording (Host Only)
@login_required(login_url='/register/')
@require_POST
def start_recording(request, room_code):
    """Start Agora Cloud Recording for the meeting"""
    try:
        # Validate credentials are set
        if not settings.AGORA_CUSTOMER_ID or settings.AGORA_CUSTOMER_ID == 'your_customer_id_here':
            return JsonResponse({
                'error': 'Agora Cloud Recording not configured. Please add AGORA_CUSTOMER_ID and AGORA_CUSTOMER_SECRET to .env file. See CLOUD_RECORDING_SETUP.md for details.'
            }, status=500)
        
        if not settings.AWS_ACCESS_KEY_ID or settings.AWS_ACCESS_KEY_ID == 'your_aws_access_key_here':
            return JsonResponse({
                'error': 'AWS S3 not configured. Please add AWS credentials to .env file. See CLOUD_RECORDING_SETUP.md for details.'
            }, status=500)
        
        room = get_object_or_404(MeetingRoom, room_code=room_code)
        
        # Only host can start recording
        if room.host != request.user:
            return JsonResponse({'error': 'Only the host can start recording'}, status=403)
        
        recording = room.get_recording()

        # Check if already recording
        if recording.recording_status == 'recording':
            return JsonResponse({'error': 'Recording already in progress'}, status=400)
        
        # Generate unique UID for recording bot (use a large number to avoid conflicts)
        recording_uid = 999000000 + room.id
        
        # Get channel name (same as room_id)
        channel_name = str(room.room_id)
        
        # Generate token for recording bot
        appID = settings.AGORA_APP_ID
        appCertificate = settings.AGORA_APP_CERTIFICATE
        expireTimeInSeconds = 3600
        currentTimestamp = int(time.time())
        privilegeExpiredTs = currentTimestamp + expireTimeInSeconds
        
        recording_token = RtcTokenBuilder.buildTokenWithAccount(
            appID, appCertificate, channel_name, str(recording_uid), 
            Role_Attendee, privilegeExpiredTs
        )
        
        # Initialize cloud recording
        cloud_recording = AgoraCloudRecording()
        
        # Step 1: Acquire resource
        acquire_result = cloud_recording.acquire_resource(channel_name, recording_uid)
        
        if not acquire_result['success']:
            return JsonResponse({
                'error': 'Failed to acquire recording resource',
                'details': acquire_result.get('error')
            }, status=500)
        
        resource_id = acquire_result['resourceId']
        
        # Step 2: Start recording
        start_result = cloud_recording.start_recording(
            channel_name=channel_name,
            uid=recording_uid,
            resource_id=resource_id,
            token=recording_token,
            bucket_name=settings.AWS_STORAGE_BUCKET_NAME,
            bucket_access_key=settings.AWS_ACCESS_KEY_ID,
            bucket_secret_key=settings.AWS_SECRET_ACCESS_KEY,
            bucket_region=settings.AWS_S3_REGION_NAME
        )
        
        if not start_result['success']:
            return JsonResponse({
                'error': 'Failed to start recording',
                'details': start_result.get('error'),
                'response': start_result.get('response')
            }, status=500)
        
        # Update recording info
        recording.recording_enabled = True
        recording.recording_status = 'recording'
        recording.recording_sid = start_result['sid']
        recording.recording_resource_id = resource_id
        recording.recording_uid = recording_uid
        recording.save()
        
        return JsonResponse({
            'message': 'Recording started successfully',
            'sid': start_result['sid'],
            'resourceId': resource_id
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# Stop Cloud Recording (Host Only)
@login_required(login_url='/register/')
@require_POST
def stop_recording(request, room_code):
    """Stop Agora Cloud Recording and update S3 URL"""
    try:
        room = get_object_or_404(MeetingRoom, room_code=room_code)
        
        # Only host can stop recording
        if room.host != request.user:
            return JsonResponse({'error': 'Only the host can stop recording'}, status=403)
        
        recording = room.get_recording()

        # Check if recording is active
        if recording.recording_status != 'recording':
            return JsonResponse({'error': 'No active recording found'}, status=400)
        
        if not recording.recording_sid or not recording.recording_resource_id:
            return JsonResponse({'error': 'Missing recording session data'}, status=400)
        
        # Initialize cloud recording
        cloud_recording = AgoraCloudRecording()
        
        # Stop recording
        stop_result = cloud_recording.stop_recording(
            channel_name=str(room.room_id),
            uid=recording.recording_uid,
            resource_id=recording.recording_resource_id,
            sid=recording.recording_sid
        )
        
        if not stop_result['success']:
            return JsonResponse({
                'error': 'Failed to stop recording',
                'details': stop_result.get('error')
            }, status=500)
        
        # Get recording file info from response
        server_response = stop_result.get('serverResponse', {})
        file_list = server_response.get('fileList', [])
        
        # Update recording status
        recording.recording_status = 'completed'
        
        # Generate S3 URL if files are available
        if file_list:
            # Get the first MP4 file (or HLS if no MP4)
            recording_file = None
            for file_info in file_list:
                filename = file_info.get('fileName', '')
                if filename.endswith('.mp4'):
                    recording_file = filename
                    break
            
            if not recording_file and file_list:
                recording_file = file_list[0].get('fileName')
            
            if recording_file:
                # Construct S3 URL
                s3_manager = S3Manager()
                s3_key = f"recordings/{recording_file}"
                recording.s3_recording_url = s3_manager.get_s3_url(s3_key)
        
            recording.save()
        
        return JsonResponse({
            'message': 'Recording stopped successfully',
            'fileList': file_list,
            's3_url': recording.s3_recording_url
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# Query Recording Status
@login_required(login_url='/register/')
def query_recording(request, room_code):
    """Query the current status of cloud recording"""
    try:
        room = get_object_or_404(MeetingRoom, room_code=room_code)
        
        recording = room.get_recording()

        if not recording.recording_resource_id or not recording.recording_sid:
            return JsonResponse({'error': 'No recording session found'}, status=400)
        
        cloud_recording = AgoraCloudRecording()
        
        query_result = cloud_recording.query_recording(
            resource_id=recording.recording_resource_id,
            sid=recording.recording_sid
        )
        
        if not query_result['success']:
            return JsonResponse({
                'error': 'Failed to query recording',
                'details': query_result.get('error')
            }, status=500)
        
        return JsonResponse({
            'status': recording.recording_status,
            'serverResponse': query_result.get('serverResponse', {})
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# Upload Meeting Recording (Local Audio Recording for Testing)
@login_required(login_url='/register/')
@require_POST
def upload_recording(request, room_code):
    """Upload locally recorded audio to project directory"""
    try:
        room = get_object_or_404(MeetingRoom, room_code=room_code)
        
        # Only host can upload recordings
        if room.host != request.user:
            return JsonResponse({'error': 'Only the host can upload recordings'}, status=403)
        
        if 'recording' not in request.FILES:
            return JsonResponse({'error': 'No recording file provided'}, status=400)
        
        recording_file = request.FILES['recording']
        duration = request.POST.get('duration', 0)
        
        # Generate filename with timestamp
        timestamp = int(time.time())
        filename = f"{room_code}_{timestamp}.webm"
        
        # Save the audio recording
        from django.core.files.storage import default_storage
        file_path = f"recordings/{filename}"
        saved_path = default_storage.save(file_path, ContentFile(recording_file.read()))
        
        # Get full file path
        full_path = default_storage.path(saved_path)

        recording = room.get_recording()
        transcript = room.get_transcript()

        # Try to upload to S3 if configured
        s3_url = None
        s3_error = None
        presigned_url = None
        if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY and settings.AWS_STORAGE_BUCKET_NAME:
            try:
                s3_manager = S3Manager()
                s3_key = f"recordings/{filename}"
                uploaded = s3_manager.upload_file(full_path, s3_key)
                if uploaded:
                    s3_url = s3_manager.get_s3_url(s3_key)
                    presigned_url = s3_manager.generate_presigned_url(s3_key)
                    recording.s3_recording_url = s3_url
                else:
                    s3_error = "S3 upload failed"
            except Exception as upload_error:
                s3_error = str(upload_error)

        # Transcribe with AssemblyAI (use presigned URL for private buckets)
        transcript_text = None
        transcript_status = 'not_started'
        transcript_id = None
        transcript_error = None
        if settings.ASSEMBLYAI_API_KEY and (presigned_url or s3_url):
            try:
                assembly_client = AssemblyAIClient()
                audio_url = presigned_url or s3_url
                start_data = assembly_client.start_transcription(audio_url)
                transcript_id = start_data.get('id')
                transcript_status = start_data.get('status', 'processing')

                if transcript_id:
                    result = assembly_client.wait_for_transcription(transcript_id, timeout_seconds=60, poll_interval=3)
                    transcript_status = result.get('status', transcript_status)
                    if transcript_status == 'completed':
                        transcript_text = result.get('text')
                    elif transcript_status == 'failed':
                        transcript_error = result.get('error')
            except Exception as transcribe_error:
                transcript_status = 'failed'
                transcript_error = str(transcribe_error)

        # Update recording and transcript info
        recording.recording_enabled = True
        recording.recording_duration = int(float(duration))
        recording.recording_status = 'completed'
        recording.save()

        transcript.transcript_text = transcript_text
        transcript.transcript_status = transcript_status
        transcript.transcript_id = transcript_id
        transcript.save()

        rag_enqueued = False
        if transcript_status == 'completed' and transcript_text:
            async_task('agora.rag_utils.process_transcript_for_rag', room.id)
            rag_enqueued = True

        response_data = {
            'message': 'Audio recording saved successfully',
            'filename': filename,
            'duration': duration,
            'file_path': saved_path,
            'full_path': full_path,
            'size_bytes': recording_file.size,
            's3_url': s3_url,
            's3_error': s3_error,
            'transcript_status': transcript_status,
            'transcript_id': transcript_id,
            'transcript_error': transcript_error,
            'rag_enqueued': rag_enqueued
        }
        return JsonResponse(response_data)
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error uploading recording: {error_details}")
        return JsonResponse({'error': str(e), 'details': error_details}, status=500)


# Upload External Document/Audio
@login_required(login_url='/register/')
@require_POST
def upload_document(request, room_code):
    """Upload external data (pdf/txt/doc/docx/mp3) for RAG"""
    try:
        room = get_object_or_404(MeetingRoom, room_code=room_code)

        if room.host != request.user:
            return JsonResponse({'error': 'Only the host can upload documents'}, status=403)

        if 'document' not in request.FILES:
            return JsonResponse({'error': 'No document file provided'}, status=400)

        uploaded_file = request.FILES['document']
        original_name = uploaded_file.name
        _, ext = os.path.splitext(original_name)
        ext = ext.lower()

        timestamp = int(time.time())
        safe_name = f"{room_code}_{timestamp}{ext}"

        from django.core.files.storage import default_storage
        file_path = f"documents/{safe_name}"
        saved_path = default_storage.save(file_path, ContentFile(uploaded_file.read()))
        full_path = default_storage.path(saved_path)

        document = DocumentUpload.objects.create(
            meeting=room,
            uploaded_by=request.user,
            file_name=original_name,
            file_type=ext.lstrip('.'),
            storage_path=saved_path,
            status='uploaded'
        )

        task_id = async_task('agora.tasks.process_document_upload', document.id)
        document.status = 'queued'
        document.save(update_fields=["status"])

        return JsonResponse({
            'message': 'Document queued for processing',
            'document_id': document.id,
            'file_name': document.file_name,
            'file_type': document.file_type,
            'status': document.status,
            'task_id': task_id
        })

    except Exception as e:
        if 'document' in locals():
            document.status = 'failed'
            document.error_message = str(e)
            document.save(update_fields=["status", "error_message"])
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def list_documents(request, meeting_id):
    """Return document upload statuses for a meeting."""
    try:
        meeting = get_object_or_404(MeetingRoom, id=meeting_id)

        if meeting.host != request.user:
            return JsonResponse({'error': 'Only host can view documents'}, status=403)

        documents = DocumentUpload.objects.filter(meeting=meeting).order_by('-created_at')
        data = [
            {
                'id': doc.id,
                'file_name': doc.file_name,
                'file_type': doc.file_type,
                'status': doc.status,
                's3_url': doc.s3_url,
                'chunk_count': doc.chunk_count,
                'error_message': doc.error_message,
                'created_at': doc.created_at.isoformat(),
                'processed_at': doc.processed_at.isoformat() if doc.processed_at else None
            }
            for doc in documents
        ]

        return JsonResponse({'success': True, 'documents': data})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def documents_page(request, room_code):
    room = get_object_or_404(MeetingRoom, room_code=room_code, is_active=True)
    if room.host != request.user:
        return redirect('meeting', room_code=room.room_code)

    return render(request, 'agora/documents.html', {
        'room': room,
        'meeting_db_id': room.id
    })


# Chat History (Dashboard)
@login_required(login_url='/register/')
@require_http_methods(["GET", "POST"])
def chat_messages(request):
    if request.method == "GET":
        messages = ChatMessage.objects.select_related('user').order_by('-created_at')[:50]
        data = [
            {
                'id': msg.id,
                'user': msg.user.username,
                'content': msg.content,
                'created_at': msg.created_at.isoformat()
            }
            for msg in reversed(messages)
        ]
        return JsonResponse({'messages': data})

    # POST - create new message
    try:
        payload = json.loads(request.body.decode('utf-8'))
        content = payload.get('content', '').strip()
        if not content:
            return JsonResponse({'error': 'Message content is required'}, status=400)

        msg = ChatMessage.objects.create(user=request.user, content=content)
        return JsonResponse({
            'id': msg.id,
            'user': msg.user.username,
            'content': msg.content,
            'created_at': msg.created_at.isoformat()
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def prepare_meeting_for_rag(request, meeting_id):
    """
    Process transcript for RAG: chunk and create embeddings
    GET /api/meetings/{meeting_id}/prepare-rag/
    """
    try:
        meeting = get_object_or_404(MeetingRoom, id=meeting_id)
        
        # Only allow host to trigger
        if meeting.host != request.user:
            return JsonResponse({'error': 'Only host can prepare for RAG'}, status=403)
        
        transcript = meeting.get_transcript()

        # Check if transcript is ready
        if transcript.transcript_status != 'completed':
            return JsonResponse({
                'error': 'Transcript not yet completed',
                'status': transcript.transcript_status
            }, status=400)
        
        # Process for RAG
        result = process_transcript_for_rag(meeting.id)
        
        if result['success']:
            return JsonResponse({
                'success': True,
                'message': result['message'],
                'chunk_count': result['chunk_count']
            })
        else:
            return JsonResponse({
                'success': False,
                'error': result['error']
            }, status=500)
    
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


async def query_meeting_transcript(request, meeting_id):
    """
    Query a meeting transcript using RAG with conversation context
    POST /api/meetings/{meeting_id}/query/
    Body: {'question': 'user question'}
    """
    try:
        if request.method != 'POST':
            return HttpResponseNotAllowed(['POST'])
        is_authenticated = await sync_to_async(lambda: request.user.is_authenticated)()
        if not is_authenticated:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        meeting = await sync_to_async(get_object_or_404)(MeetingRoom, id=meeting_id)
        payload = json.loads(request.body.decode('utf-8'))
        question = payload.get('question', '').strip()
        
        if not question:
            return JsonResponse({'error': 'Question is required'}, status=400)
        
        # Check if meeting is prepared for RAG (transcript or documents)
        has_doc_chunks = await sync_to_async(
            DocumentChunk.objects.filter(document__meeting=meeting).exists
        )()
        rag_state = await sync_to_async(meeting.get_rag_state)()
        if not rag_state.embeddings_created_at and not has_doc_chunks:
            return JsonResponse({
                'error': 'Meeting data not yet processed for RAG. Upload a document or prepare transcript.',
                'status': 'not_prepared'
            }, status=400)
        
        stream = request.GET.get('stream') == 'true'
        user_id = await sync_to_async(lambda: request.user.id)()

        if stream:
            stream_gen, _ = await stream_rag_response_async(
                meeting_id=meeting.id,
                user_id=user_id,
                query=question,
                top_k=5
            )
            return StreamingHttpResponse(stream_gen, content_type='text/plain; charset=utf-8')

        response_text, relevant_chunks = await sync_to_async(generate_rag_response)(
            meeting_id=meeting.id,
            user_id=user_id,
            query=question,
            top_k=5
        )
        
        return JsonResponse({
            'success': True,
            'response': response_text,
            'relevant_chunks': [
                {
                    'index': chunk['chunk_index'],
                    'text': chunk['text'],
                    'score': round(chunk['score'], 3),
                    'start_time': chunk.get('start_time'),
                    'end_time': chunk.get('end_time'),
                    'source_type': chunk.get('source_type'),
                    'meeting_title': chunk.get('meeting_title'),
                    'document_id': chunk.get('document_id'),
                    'document_name': chunk.get('document_name')
                }
                for chunk in relevant_chunks
            ]
        })
    
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


async def query_global_rag(request):
    """Query across all meetings and documents for the user."""
    try:
        if request.method != 'POST':
            return HttpResponseNotAllowed(['POST'])
        is_authenticated = await sync_to_async(lambda: request.user.is_authenticated)()
        if not is_authenticated:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        payload = json.loads(request.body.decode('utf-8'))
        question = payload.get('question', '').strip()

        if not question:
            return JsonResponse({'error': 'Question is required'}, status=400)

        stream = request.GET.get('stream') == 'true'
        user_id = await sync_to_async(lambda: request.user.id)()

        if stream:
            stream_gen, _ = await stream_rag_response_async(
                meeting_id=None,
                user_id=user_id,
                query=question,
                top_k=5
            )
            return StreamingHttpResponse(stream_gen, content_type='text/plain; charset=utf-8')

        response_text, relevant_chunks = await sync_to_async(generate_rag_response)(
            meeting_id=None,
            user_id=user_id,
            query=question,
            top_k=5
        )

        return JsonResponse({
            'success': True,
            'response': response_text,
            'relevant_chunks': [
                {
                    'index': chunk['chunk_index'],
                    'text': chunk['text'],
                    'score': round(chunk['score'], 3),
                    'start_time': chunk.get('start_time'),
                    'end_time': chunk.get('end_time'),
                    'source_type': chunk.get('source_type'),
                    'meeting_title': chunk.get('meeting_title'),
                    'document_id': chunk.get('document_id'),
                    'document_name': chunk.get('document_name')
                }
                for chunk in relevant_chunks
            ]
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required(login_url='/register/')
@require_http_methods(["GET"])
def google_llm_health(request):
    """
    Health-check for Google LLM configuration.
    GET /api/health/google/
    """
    if not settings.GOOGLE_API_KEY:
        return JsonResponse({'ok': False, 'error': 'GOOGLE_API_KEY is not configured'}, status=503)

    model_name = settings.GOOGLE_GENERATE_MODEL
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent?key={settings.GOOGLE_API_KEY}"
    )
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": "Reply with OK"}]
            }
        ],
        "generationConfig": {
            "maxOutputTokens": 8,
            "temperature": 0.0
        }
    }

    started = time.time()
    try:
        response = requests.post(
            url,
            json=payload,
            timeout=(settings.GOOGLE_CONNECT_TIMEOUT, settings.GOOGLE_READ_TIMEOUT)
        )
        response.raise_for_status()
        data = response.json()

        text_parts = []
        for candidate in data.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                part_text = part.get("text")
                if part_text:
                    text_parts.append(part_text)

        output = "".join(text_parts).strip()
        latency_ms = int((time.time() - started) * 1000)
        return JsonResponse({
            'ok': True,
            'model': model_name,
            'latency_ms': latency_ms,
            'output': output
        })
    except requests.exceptions.ReadTimeout as e:
        logger.error("Google health-check timed out: %s", str(e))
        return JsonResponse({
            'ok': False,
            'model': model_name,
            'error': 'Google request timed out'
        }, status=503)
    except requests.exceptions.RequestException as e:
        status = getattr(e.response, "status_code", None)
        body = getattr(e.response, "text", "")
        logger.error("Google health-check failed (status=%s): %s", status, body[:1000])
        return JsonResponse({
            'ok': False,
            'model': model_name,
            'error': 'Google request failed'
        }, status=503)
    except ValueError as e:
        logger.error("Google health-check invalid JSON response: %s", str(e))
        return JsonResponse({
            'ok': False,
            'model': model_name,
            'error': 'Invalid JSON response from Google'
        }, status=503)
    except Exception as e:
        logger.error("Google health-check unexpected error: %s", str(e))
        return JsonResponse({
            'ok': False,
            'model': model_name,
            'error': str(e)
        }, status=503)


@login_required
@require_http_methods(["GET"])
def get_conversation_history(request, meeting_id):
    """
    Get conversation history for a meeting
    GET /api/meetings/{meeting_id}/conversation-history/
    """
    try:
        from .models import ConversationHistory
        
        meeting = get_object_or_404(MeetingRoom, id=meeting_id)
        
        history = ConversationHistory.objects.filter(
            meeting=meeting,
            user=request.user
        ).order_by('created_at')
        
        return JsonResponse({
            'success': True,
            'conversation': [
                {
                    'id': item.id,
                    'question': item.user_question,
                    'response': item.assistant_response,
                    'created_at': item.created_at.isoformat(),
                    'relevant_chunks': item.relevant_chunks
                }
                for item in history
            ]
        })
    
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET", "POST"])
def meeting_agenda(request, meeting_id):
    """Get or add agenda points for a meeting."""
    meeting = get_object_or_404(MeetingRoom, id=meeting_id)

    if request.method == "POST":
        try:
            payload = json.loads(request.body.decode('utf-8'))
            text = payload.get('text', '').strip()
            if not text:
                return JsonResponse({'error': 'Text is required'}, status=400)
            max_order = meeting.agenda_points.aggregate(models.Max('order')).get('order__max') or 0
            point = MeetingAgendaPoint.objects.create(
                meeting=meeting,
                text=text,
                order=max_order + 1,
                created_by=request.user,
                is_ai_generated=False
            )
            return JsonResponse({
                'id': point.id,
                'text': point.text,
                'order': point.order,
                'is_ai_generated': point.is_ai_generated
            })
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    points = list(meeting.agenda_points.all())
    if not points:
        generated = generate_agenda_points(meeting.title, meeting.description, meeting.id)
        for idx, text in enumerate(generated, start=1):
            MeetingAgendaPoint.objects.create(
                meeting=meeting,
                text=text,
                order=idx,
                created_by=None,
                is_ai_generated=True
            )
        points = list(meeting.agenda_points.all())

    return JsonResponse({
        'points': [
            {
                'id': point.id,
                'text': point.text,
                'order': point.order,
                'is_ai_generated': point.is_ai_generated
            }
            for point in points
        ]
    })


@login_required
@require_http_methods(["POST", "DELETE"])
def delete_agenda_point(request, meeting_id, point_id):
    """Remove an agenda point and resequence ordering."""
    meeting = get_object_or_404(MeetingRoom, id=meeting_id)
    point = get_object_or_404(MeetingAgendaPoint, id=point_id, meeting=meeting)
    point.delete()

    remaining = list(meeting.agenda_points.order_by('order', 'created_at'))
    for idx, item in enumerate(remaining, start=1):
        if item.order != idx:
            item.order = idx
            item.save(update_fields=['order'])

    return JsonResponse({
        'success': True,
        'points': [
            {
                'id': item.id,
                'text': item.text,
                'order': item.order,
                'is_ai_generated': item.is_ai_generated
            }
            for item in remaining
        ]
    })
