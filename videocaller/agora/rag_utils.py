"""RAG (Retrieval-Augmented Generation) service for intelligent query responses"""
import json
import logging
import queue
import threading
from typing import Iterable, List, Dict, Tuple
import requests
from django.conf import settings
from asgiref.sync import sync_to_async
from .embedding_utils import search_similar_chunks
from .models import ConversationHistory

logger = logging.getLogger(__name__)

GOOGLE_API_KEY = getattr(settings, 'GOOGLE_API_KEY', '')
GOOGLE_GENERATE_MODEL = getattr(settings, 'GOOGLE_GENERATE_MODEL', 'gemini-2.5-flash-lite')
GOOGLE_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models/"
GOOGLE_CONNECT_TIMEOUT = getattr(settings, 'GOOGLE_CONNECT_TIMEOUT', 10)
GOOGLE_READ_TIMEOUT = getattr(settings, 'GOOGLE_READ_TIMEOUT', 600)
MAX_TOKENS = getattr(settings, 'GOOGLE_MAX_TOKENS', 1000)
MAX_CONVERSATION_TURNS = 5  # Limit context window


def _build_google_prompt(system_prompt: str, conversation_context: List[Dict], query: str) -> str:
    parts: List[str] = ["SYSTEM:", system_prompt.strip()]
    if conversation_context:
        parts.append("\nCONVERSATION:")
        for item in conversation_context:
            role = "ASSISTANT" if item["role"] == "assistant" else "USER"
            parts.append(f"{role}: {item['content'].strip()}")
    parts.append("\nUSER QUESTION:")
    parts.append(query.strip())
    parts.append("\nASSISTANT:")
    return "\n".join(parts)


def _google_generate(prompt: str) -> str:
    if not GOOGLE_API_KEY:
        raise ValueError("GOOGLE_API_KEY is not configured")

    url = f"{GOOGLE_API_BASE}{GOOGLE_GENERATE_MODEL}:generateContent?key={GOOGLE_API_KEY}"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}]
            }
        ],
        "generationConfig": {
            "maxOutputTokens": MAX_TOKENS,
            "temperature": 0.7
        }
    }
    try:
        response = requests.post(
            url,
            json=payload,
            timeout=(GOOGLE_CONNECT_TIMEOUT, GOOGLE_READ_TIMEOUT)
        )
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.ReadTimeout as e:
        logger.error("Google generate timed out: %s", str(e))
        raise
    except requests.exceptions.RequestException as e:
        status = getattr(e.response, "status_code", None)
        body = getattr(e.response, "text", "")
        logger.error("Google generate request failed (status=%s): %s", status, body[:1000])
        raise
    except ValueError as e:
        logger.error("Google generate invalid JSON response: %s", str(e))
        raise

    text_parts: List[str] = []
    for candidate in data.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            part_text = part.get("text")
            if part_text:
                text_parts.append(part_text)
    return "".join(text_parts).strip()


def _google_generate_stream(prompt: str) -> Iterable[str]:
    if not GOOGLE_API_KEY:
        raise ValueError("GOOGLE_API_KEY is not configured")

    url = f"{GOOGLE_API_BASE}{GOOGLE_GENERATE_MODEL}:streamGenerateContent?key={GOOGLE_API_KEY}"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}]
            }
        ],
        "generationConfig": {
            "maxOutputTokens": MAX_TOKENS,
            "temperature": 0.7
        }
    }
    try:
        with requests.post(
            url,
            json=payload,
            stream=True,
            timeout=(GOOGLE_CONNECT_TIMEOUT, GOOGLE_READ_TIMEOUT)
        ) as response:
            response.raise_for_status()
            buffered_lines: List[str] = []
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    for candidate in data.get("candidates", []):
                        for part in candidate.get("content", {}).get("parts", []):
                            part_text = part.get("text")
                            if part_text:
                                yield part_text
                    continue
                except json.JSONDecodeError:
                    buffered_lines.append(line)

            if buffered_lines:
                buffered_payload = "\n".join(buffered_lines).strip()
                try:
                    data = json.loads(buffered_payload)
                    if isinstance(data, list):
                        items = data
                    else:
                        items = [data]
                    for item in items:
                        for candidate in item.get("candidates", []):
                            for part in candidate.get("content", {}).get("parts", []):
                                part_text = part.get("text")
                                if part_text:
                                    yield part_text
                except json.JSONDecodeError:
                    logger.warning("Google stream buffered payload was not JSON")
    except requests.exceptions.ReadTimeout as e:
        logger.error("Google stream timed out: %s", str(e))
        yield "\n[Model timed out. Try again.]"
    except requests.exceptions.RequestException as e:
        status = getattr(e.response, "status_code", None)
        body = getattr(e.response, "text", "")
        logger.error("Google stream request failed (status=%s): %s", status, body[:1000])
        yield "\n[Model error. Please try again.]"


def get_conversation_context(meeting_id: int | None, user_id: int, limit: int = MAX_CONVERSATION_TURNS) -> List[Dict]:
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
        history_query = ConversationHistory.objects.filter(user_id=user_id)
        if meeting_id is not None:
            history_query = history_query.filter(meeting_id=meeting_id)

        history = history_query.order_by('-created_at')[:limit]
        
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


def _save_conversation_turn(
    meeting_id: int | None,
    user_id: int,
    query: str,
    assistant_response: str,
    relevant_chunks: List[Dict]
) -> None:
    if meeting_id is None:
        return

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


def generate_rag_response(
    meeting_id: int | None,
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
            return "Sorry, I couldn't find relevant information in the available documents or transcripts.", []
        
        # Step 2: Get conversation history for context
        conversation_context = get_conversation_context(meeting_id, user_id)
        
        # Step 3: Build system prompt
        chunks_text = "\n\n".join([
            f"[Source: {chunk.get('source_type', 'meeting_transcript')}, "
            f"Chunk {chunk['chunk_index']}, "
            f"Doc: {chunk.get('document_name', 'N/A')}] {chunk['text']}"
            for chunk in relevant_chunks
        ])
        
        system_prompt = f"""You are a helpful assistant answering questions from meeting transcripts and uploaded documents. 
        
You have access to relevant parts of a transcript provided below. Use this context to answer user questions accurately and concisely.
If the information is not in the provided context, say you don't have that information from the transcript.

RELEVANT TRANSCRIPT SECTIONS:
{chunks_text}

Answer the user's question based ONLY on the provided transcript sections. Be specific and cite which part of the transcript you're referring to when possible."""
        
        # Step 4: Build prompt for Google
        prompt = _build_google_prompt(system_prompt, conversation_context, query)

        # Step 5: Call Google
        assistant_response = _google_generate(prompt)

        # Step 6: Save conversation turn (for next context)
        _save_conversation_turn(meeting_id, user_id, query, assistant_response, relevant_chunks)
        
        return assistant_response, relevant_chunks
    
    except Exception as e:
        logger.error(f"Error generating RAG response: {str(e)}")
        raise


def stream_rag_response(
    meeting_id: int | None,
    user_id: int,
    query: str,
    top_k: int = 5
) -> Tuple[Iterable[str], List[Dict]]:
    try:
        relevant_chunks = search_similar_chunks(query, meeting_id, top_k)

        if not relevant_chunks:
            return iter(["Sorry, I couldn't find relevant information in the available documents or transcripts."]), []

        conversation_context = get_conversation_context(meeting_id, user_id)
        chunks_text = "\n\n".join([
            f"[Source: {chunk.get('source_type', 'meeting_transcript')}, "
            f"Chunk {chunk['chunk_index']}, "
            f"Doc: {chunk.get('document_name', 'N/A')}] {chunk['text']}"
            for chunk in relevant_chunks
        ])
        system_prompt = f"""You are a helpful assistant answering questions from meeting transcripts and uploaded documents. 
        
You have access to relevant parts of a transcript provided below. Use this context to answer user questions accurately and concisely.
If the information is not in the provided context, say you don't have that information from the transcript.

RELEVANT TRANSCRIPT SECTIONS:
{chunks_text}

Answer the user's question based ONLY on the provided transcript sections. Be specific and cite which part of the transcript you're referring to when possible."""

        prompt = _build_google_prompt(system_prompt, conversation_context, query)

        def generator() -> Iterable[str]:
            yield "Thinking...\n"
            parts: List[str] = []
            for token in _google_generate_stream(prompt):
                parts.append(token)
                yield token
            assistant_response = "".join(parts)
            _save_conversation_turn(meeting_id, user_id, query, assistant_response, relevant_chunks)

        return generator(), relevant_chunks
    except Exception as e:
        logger.error(f"Error streaming RAG response: {str(e)}")
        raise


async def stream_rag_response_async(
    meeting_id: int | None,
    user_id: int,
    query: str,
    top_k: int = 5
) -> Tuple[Iterable[str], List[Dict]]:
    try:
        relevant_chunks = await sync_to_async(search_similar_chunks)(query, meeting_id, top_k)

        if not relevant_chunks:
            return iter(["Sorry, I couldn't find relevant information in the available documents or transcripts."]), []

        conversation_context = await sync_to_async(get_conversation_context)(meeting_id, user_id)
        chunks_text = "\n\n".join([
            f"[Source: {chunk.get('source_type', 'meeting_transcript')}, "
            f"Chunk {chunk['chunk_index']}, "
            f"Doc: {chunk.get('document_name', 'N/A')}] {chunk['text']}"
            for chunk in relevant_chunks
        ])
        system_prompt = f"""You are a helpful assistant answering questions from meeting transcripts and uploaded documents. 
        
You have access to relevant parts of a transcript provided below. Use this context to answer user questions accurately and concisely.
If the information is not in the provided context, say you don't have that information from the transcript.

RELEVANT TRANSCRIPT SECTIONS:
{chunks_text}

Answer the user's question based ONLY on the provided transcript sections. Be specific and cite which part of the transcript you're referring to when possible."""

        prompt = _build_google_prompt(system_prompt, conversation_context, query)
        token_queue: queue.Queue = queue.Queue()
        stop_marker = object()

        def worker():
            try:
                for token in _google_generate_stream(prompt):
                    token_queue.put(token)
            except Exception:
                token_queue.put("\n[Model error. Please try again.]")
            finally:
                token_queue.put(stop_marker)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        def generator() -> Iterable[str]:
            parts: List[str] = []
            yield "Thinking...\n"
            while True:
                item = token_queue.get()
                if item is stop_marker:
                    break
                parts.append(item)
                yield item
            assistant_response = "".join(parts)
            _save_conversation_turn(meeting_id, user_id, query, assistant_response, relevant_chunks)

        return generator(), relevant_chunks
    except Exception as e:
        logger.error(f"Error streaming RAG response (async): {str(e)}")
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
        transcript = meeting.get_transcript()
        rag_state = meeting.get_rag_state()
        
        if not transcript.transcript_text:
            logger.error(f"No transcript text found for meeting {meeting_id}")
            return {"success": False, "error": "No transcript text"}
        
        # Check if already processed
        if rag_state.chunks_created_at and rag_state.embeddings_created_at:
            logger.info(f"Meeting {meeting_id} already processed for RAG")
            return {"success": True, "message": "Already processed", "chunk_count": 0}
        
        # Step 1: Chunk the transcript
        chunks = chunk_transcript(transcript.transcript_text)
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
        rag_state.chunks_created_at = timezone.now()
        rag_state.embeddings_created_at = timezone.now()
        rag_state.save()
        
        return {
            "success": True,
            "chunk_count": len(chunks),
            "message": f"Successfully processed {len(chunks)} chunks"
        }
    
    except Exception as e:
        logger.error(f"Error processing transcript for RAG: {str(e)}")
        return {"success": False, "error": str(e)}
