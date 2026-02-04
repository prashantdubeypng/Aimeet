from django.urls import path
from . import views
from django.contrib.auth.views import LoginView, LogoutView

urlpatterns = [
    # Authentication
    path('register/', views.register, name='register'),
    path('login/', LoginView.as_view(template_name='agora/login.html'), name='login'),
    path('logout/', LogoutView.as_view(next_page='login'), name='logout'),
    
    # Home & Room Management
    path('', views.home, name='home'),
    path('create/', views.create_room, name='create_room'),
    path('join/', views.join_room, name='join_room'),
    
    # Meeting
    path('meeting/<str:room_code>/', views.meeting, name='meeting'),
    path('meeting/<str:room_code>/end/', views.end_meeting, name='end_meeting'),
    path('meeting/<str:room_code>/upload-recording/', views.upload_recording, name='upload_recording'),
    
    # Cloud Recording Endpoints
    path('meeting/<str:room_code>/start-recording/', views.start_recording, name='start_recording'),
    path('meeting/<str:room_code>/stop-recording/', views.stop_recording, name='stop_recording'),
    path('meeting/<str:room_code>/query-recording/', views.query_recording, name='query_recording'),
    
    # API Endpoints
    path('pusher/auth/', views.pusher_auth, name='agora-pusher-auth'),
    path('token/', views.generate_agora_token, name='agora-token'),
    path('chat/messages/', views.chat_messages, name='chat_messages'),
    
    # RAG Endpoints
    path('api/meetings/<int:meeting_id>/prepare-rag/', views.prepare_meeting_for_rag, name='prepare_rag'),
    path('api/meetings/<int:meeting_id>/query/', views.query_meeting_transcript, name='query_transcript'),
    path('api/meetings/<int:meeting_id>/conversation-history/', views.get_conversation_history, name='conversation_history'),
]
