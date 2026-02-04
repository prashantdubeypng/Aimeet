import os
import time
import json
import random
import string

from django.http.response import JsonResponse
from django.contrib.auth import get_user_model, authenticate, login
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST, require_http_methods
from django.contrib.auth.forms import UserCreationForm
from django.db.models import Q
from django.core.files.base import ContentFile
from django.conf import settings

from .agora_key.RtcTokenBuilder import RtcTokenBuilder, Role_Attendee
from .models import MeetingRoom, ChatMessage
from .recording_utils import AgoraCloudRecording, S3Manager
from .assemblyai_utils import AssemblyAIClient
from .rag_utils import generate_rag_response, process_transcript_for_rag
from pusher import Pusher


# Instantiate a Pusher Client
pusher_client = Pusher(app_id=(os.environ.get('PUSHER_APP_ID')),
                       key=os.environ.get('PUSHER_KEY'),
                       secret=os.environ.get('PUSHER_SECRET'),
                       ssl=True,
                       cluster=os.environ.get('PUSHER_CLUSTER')
                       )


def generate_room_code():
    """Generate a unique 9-character room code like abc-def-ghi"""
    chars = string.ascii_lowercase + string.digits
    code = '-'.join([''.join(random.choices(chars, k=3)) for _ in range(3)])
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
        'is_host': room.host == request.user
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
    payload = pusher_client.authenticate(
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
        
        # Check if already recording
        if room.recording_status == 'recording':
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
        
        # Update room with recording info
        room.recording_enabled = True
        room.recording_status = 'recording'
        room.recording_sid = start_result['sid']
        room.recording_resource_id = resource_id
        room.recording_uid = recording_uid
        room.save()
        
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
        
        # Check if recording is active
        if room.recording_status != 'recording':
            return JsonResponse({'error': 'No active recording found'}, status=400)
        
        if not room.recording_sid or not room.recording_resource_id:
            return JsonResponse({'error': 'Missing recording session data'}, status=400)
        
        # Initialize cloud recording
        cloud_recording = AgoraCloudRecording()
        
        # Stop recording
        stop_result = cloud_recording.stop_recording(
            channel_name=str(room.room_id),
            uid=room.recording_uid,
            resource_id=room.recording_resource_id,
            sid=room.recording_sid
        )
        
        if not stop_result['success']:
            return JsonResponse({
                'error': 'Failed to stop recording',
                'details': stop_result.get('error')
            }, status=500)
        
        # Get recording file info from response
        server_response = stop_result.get('serverResponse', {})
        file_list = server_response.get('fileList', [])
        
        # Update room status
        room.recording_status = 'completed'
        
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
                room.s3_recording_url = s3_manager.get_s3_url(s3_key)
        
        room.save()
        
        return JsonResponse({
            'message': 'Recording stopped successfully',
            'fileList': file_list,
            's3_url': room.s3_recording_url
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# Query Recording Status
@login_required(login_url='/register/')
def query_recording(request, room_code):
    """Query the current status of cloud recording"""
    try:
        room = get_object_or_404(MeetingRoom, room_code=room_code)
        
        if not room.recording_resource_id or not room.recording_sid:
            return JsonResponse({'error': 'No recording session found'}, status=400)
        
        cloud_recording = AgoraCloudRecording()
        
        query_result = cloud_recording.query_recording(
            resource_id=room.recording_resource_id,
            sid=room.recording_sid
        )
        
        if not query_result['success']:
            return JsonResponse({
                'error': 'Failed to query recording',
                'details': query_result.get('error')
            }, status=500)
        
        return JsonResponse({
            'status': room.recording_status,
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
                    room.s3_recording_url = s3_url
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

        # Update room with recording info
        room.recording_enabled = True
        room.recording_duration = int(float(duration))
        room.recording_status = 'completed'
        room.transcript_text = transcript_text
        room.transcript_status = transcript_status
        room.transcript_id = transcript_id
        room.save()

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
            'transcript_error': transcript_error
        }
        return JsonResponse(response_data)
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error uploading recording: {error_details}")
        return JsonResponse({'error': str(e), 'details': error_details}, status=500)


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
        
        # Check if transcript is ready
        if meeting.transcript_status != 'completed':
            return JsonResponse({
                'error': 'Transcript not yet completed',
                'status': meeting.transcript_status
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


@login_required
@require_http_methods(["POST"])
def query_meeting_transcript(request, meeting_id):
    """
    Query a meeting transcript using RAG with conversation context
    POST /api/meetings/{meeting_id}/query/
    Body: {'question': 'user question'}
    """
    try:
        meeting = get_object_or_404(MeetingRoom, id=meeting_id)
        payload = json.loads(request.body.decode('utf-8'))
        question = payload.get('question', '').strip()
        
        if not question:
            return JsonResponse({'error': 'Question is required'}, status=400)
        
        # Check if meeting is prepared for RAG
        if not meeting.embeddings_created_at:
            return JsonResponse({
                'error': 'Meeting transcript not yet processed for RAG. Call prepare-rag first.',
                'status': 'not_prepared'
            }, status=400)
        
        # Generate RAG response with conversation context
        response_text, relevant_chunks = generate_rag_response(
            meeting_id=meeting.id,
            user_id=request.user.id,
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
                    'end_time': chunk.get('end_time')
                }
                for chunk in relevant_chunks
            ]
        })
    
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


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
