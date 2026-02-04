"""RAG (Retrieval-Augmented Generation) service for intelligent query responses"""
import logging
from typing import List, Dict, Tuple
from django.conf import settings
from openai import OpenAI
from .embedding_utils import search_similar_chunks
from .models import ConversationHistory

logger = logging.getLogger(__name__)

# Initialize OpenAI client
openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)

LLM_MODEL = getattr(settings, 'OPENAI_LLM_MODEL', 'gpt-4o-mini')
MAX_TOKENS = getattr(settings, 'OPENAI_MAX_TOKENS', 1000)
MAX_CONVERSATION_TURNS = 5  # Limit context window


def get_conversation_context(meeting_id: int, user_id: int, limit: int = MAX_CONVERSATION_TURNS) -> List[Dict]:
    """
    Retrieve recent conversation history for a user in a meeting
    
    Args:
        meeting_id: ID of the meeting
        user_id: ID of the user
        limit: Number of recent turns to retrieve
    
    Returns:
        List of dicts with questions and responses
    """
    try:
        history = ConversationHistory.objects.filter(
            meeting_id=meeting_id,
            user_id=user_id
        ).order_by('-created_at')[:limit]
        
        # Reverse to get chronological order
        context = []
        for turn in reversed(history):
            context.append({
                "role": "user",
                "content": turn.user_question
            })
            context.append({
                "role": "assistant",
                "content": turn.assistant_response
            })
        
        return context
    except Exception as e:
        logger.error(f"Error retrieving conversation context: {str(e)}")
        return []


def generate_rag_response(
    meeting_id: int,
    user_id: int,
    query: str,
    top_k: int = 5
) -> Tuple[str, List[Dict]]:
    """
    Generate response using RAG: retrieve relevant chunks + conversation history + LLM
    
    Args:
        meeting_id: ID of the meeting to query
        user_id: ID of the user asking
        query: User's question
        top_k: Number of similar chunks to retrieve
    
    Returns:
        Tuple of (response_text, relevant_chunks)
    """
    try:
        # Step 1: Retrieve similar chunks from vector DB
        relevant_chunks = search_similar_chunks(query, meeting_id, top_k)
        
        if not relevant_chunks:
            logger.warning(f"No relevant chunks found for meeting {meeting_id}, query: {query}")
            return "Sorry, I couldn't find relevant information about that in the meeting transcript.", []
        
        # Step 2: Get conversation history for context
        conversation_context = get_conversation_context(meeting_id, user_id)
        
        # Step 3: Build system prompt
        chunks_text = "\n\n".join([
            f"[Chunk {chunk['chunk_index']}] {chunk['text']}"
            for chunk in relevant_chunks
        ])
        
        system_prompt = f"""You are a helpful assistant analyzing meeting transcripts. 
        
You have access to relevant parts of a transcript provided below. Use this context to answer user questions accurately and concisely.
If the information is not in the provided context, say you don't have that information from the transcript.

RELEVANT TRANSCRIPT SECTIONS:
{chunks_text}

Answer the user's question based ONLY on the provided transcript sections. Be specific and cite which part of the transcript you're referring to when possible."""
        
        # Step 4: Build messages with conversation history
        messages = [
            {"role": "system", "content": system_prompt}
        ]
        
        # Add conversation history
        messages.extend(conversation_context)
        
        # Add current query
        messages.append({
            "role": "user",
            "content": query
        })
        
        # Step 5: Call GPT-4o-mini for response
        response = openai_client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            max_tokens=MAX_TOKENS,
            temperature=0.7
        )
        
        assistant_response = response.choices[0].message.content
        
        # Step 6: Save conversation turn (for next context)
        try:
            from .models import MeetingRoom
            meeting = MeetingRoom.objects.get(id=meeting_id)
            ConversationHistory.objects.create(
                meeting=meeting,
                user_id=user_id,
                user_question=query,
                assistant_response=assistant_response,
                relevant_chunks=[chunk['chunk_index'] for chunk in relevant_chunks]
            )
        except Exception as e:
            logger.error(f"Error saving conversation history: {str(e)}")
        
        return assistant_response, relevant_chunks
    
    except Exception as e:
        logger.error(f"Error generating RAG response: {str(e)}")
        raise


def process_transcript_for_rag(meeting_id: int) -> Dict:
    """
    Process a completed transcript: chunk it and generate embeddings
    
    Args:
        meeting_id: ID of the meeting with completed transcript
    
    Returns:
        Dict with processing status and chunk count
    """
    try:
        from .models import MeetingRoom, TranscriptChunk
        from .embedding_utils import chunk_transcript, store_chunks_in_vector_db
        from django.utils import timezone
        
        meeting = MeetingRoom.objects.get(id=meeting_id)
        
        if not meeting.transcript_text:
            logger.error(f"No transcript text found for meeting {meeting_id}")
            return {"success": False, "error": "No transcript text"}
        
        # Check if already processed
        if meeting.chunks_created_at and meeting.embeddings_created_at:
            logger.info(f"Meeting {meeting_id} already processed for RAG")
            return {"success": True, "message": "Already processed", "chunk_count": 0}
        
        # Step 1: Chunk the transcript
        chunks = chunk_transcript(meeting.transcript_text)
        logger.info(f"Created {len(chunks)} chunks for meeting {meeting_id}")
        
        # Step 2: Create TranscriptChunk objects in DB
        chunk_objects = []
        for idx, chunk_text in enumerate(chunks):
            chunk_obj = TranscriptChunk.objects.create(
                meeting=meeting,
                chunk_text=chunk_text,
                chunk_index=idx
            )
            chunk_objects.append(chunk_obj)
        
        # Step 3: Store chunks and embeddings in Qdrant
        store_chunks_in_vector_db(meeting_id, chunks, chunk_objects)
        
        # Step 4: Update meeting status
        meeting.chunks_created_at = timezone.now()
        meeting.embeddings_created_at = timezone.now()
        meeting.save()
        
        return {
            "success": True,
            "chunk_count": len(chunks),
            "message": f"Successfully processed {len(chunks)} chunks"
        }
    
    except Exception as e:
        logger.error(f"Error processing transcript for RAG: {str(e)}")
        return {"success": False, "error": str(e)}
