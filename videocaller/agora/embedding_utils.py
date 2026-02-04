"""OpenAI embeddings and Qdrant vector DB management"""
import os
import json
import logging
from typing import List, Dict, Tuple
from django.conf import settings
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
import re

logger = logging.getLogger(__name__)

# Initialize clients
openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
qdrant_client = QdrantClient(url=settings.QDRANT_URL, api_key=getattr(settings, 'QDRANT_API_KEY', None))

EMBEDDING_MODEL = getattr(settings, 'OPENAI_EMBEDDING_MODEL', 'text-embedding-3-small')
EMBEDDING_DIMENSION = getattr(settings, 'OPENAI_EMBEDDING_DIMENSION', 1536)
COLLECTION_NAME = getattr(settings, 'QDRANT_COLLECTION_NAME', 'meeting_transcripts')


def ensure_collection_exists():
    """Create Qdrant collection if it doesn't exist"""
    try:
        qdrant_client.get_collection(COLLECTION_NAME)
    except Exception:
        logger.info(f"Creating Qdrant collection: {COLLECTION_NAME}")
        qdrant_client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=EMBEDDING_DIMENSION, distance=Distance.COSINE),
        )


def chunk_transcript(transcript_text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """
    Split transcript into overlapping chunks using recursive character splitting
    
    Args:
        transcript_text: Full transcript text
        chunk_size: Target tokens per chunk (approximate)
        overlap: Token overlap between chunks
    
    Returns:
        List of text chunks
    """
    # Simple recursive character splitting (approximates token count)
    # Typically 1 token ≈ 4 characters
    char_chunk_size = chunk_size * 4
    char_overlap = overlap * 4
    
    chunks = []
    
    # Split by sentences first for better coherence
    sentences = re.split(r'(?<=[.!?])\s+', transcript_text)
    
    current_chunk = ""
    for sentence in sentences:
        if len(current_chunk) + len(sentence) < char_chunk_size:
            current_chunk += (sentence + " " if current_chunk else sentence + " ")
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            # Overlap with previous chunk
            if chunks and len(current_chunk) > char_overlap:
                current_chunk = current_chunk[-char_overlap:] + sentence + " "
            else:
                current_chunk = sentence + " "
    
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    return chunks


def get_embedding(text: str) -> List[float]:
    """
    Generate embedding for text using OpenAI API
    
    Args:
        text: Text to embed
    
    Returns:
        List of floats representing the embedding vector
    """
    try:
        response = openai_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=text
        )
        embedding = response.data[0].embedding
        
        # Ensure consistent dimension
        if len(embedding) != EMBEDDING_DIMENSION:
            logger.warning(f"Embedding dimension mismatch: {len(embedding)} vs {EMBEDDING_DIMENSION}")
        
        return embedding
    except Exception as e:
        logger.error(f"Error generating embedding: {str(e)}")
        raise


def get_batch_embeddings(texts: List[str]) -> List[List[float]]:
    """
    Generate embeddings for multiple texts in a batch (more efficient)
    
    Args:
        texts: List of texts to embed
    
    Returns:
        List of embedding vectors
    """
    try:
        response = openai_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=texts
        )
        embeddings = [item.embedding for item in response.data]
        return embeddings
    except Exception as e:
        logger.error(f"Error generating batch embeddings: {str(e)}")
        raise


def store_chunks_in_vector_db(
    meeting_id: int,
    chunks: List[str],
    chunk_objects: List = None
) -> List[str]:
    """
    Store chunks and their embeddings in Qdrant
    
    Args:
        meeting_id: ID of the meeting
        chunks: List of text chunks
        chunk_objects: Optional list of TranscriptChunk model instances
    
    Returns:
        List of vector IDs stored in Qdrant
    """
    ensure_collection_exists()
    
    try:
        # Get embeddings in batch (more efficient)
        embeddings = get_batch_embeddings(chunks)
        
        # Create points for Qdrant
        points = []
        vector_ids = []
        
        for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            vector_id = f"meeting_{meeting_id}_chunk_{idx}"
            vector_ids.append(vector_id)
            
            # Store metadata as JSON
            payload = {
                "meeting_id": meeting_id,
                "chunk_index": idx,
                "text": chunk[:512],  # Truncate for storage
                "chunk_length": len(chunk)
            }
            
            if chunk_objects and idx < len(chunk_objects):
                payload["chunk_db_id"] = chunk_objects[idx].id
                if chunk_objects[idx].start_time:
                    payload["start_time"] = chunk_objects[idx].start_time
                if chunk_objects[idx].end_time:
                    payload["end_time"] = chunk_objects[idx].end_time
            
            points.append(
                PointStruct(
                    id=hash(vector_id) % (2**31),  # Convert string to integer ID
                    vector=embedding,
                    payload=payload
                )
            )
        
        # Upsert points to Qdrant
        qdrant_client.upsert(
            collection_name=COLLECTION_NAME,
            points=points
        )
        
        logger.info(f"Stored {len(chunks)} chunks for meeting {meeting_id}")
        return vector_ids
    
    except Exception as e:
        logger.error(f"Error storing chunks in vector DB: {str(e)}")
        raise


def search_similar_chunks(query: str, meeting_id: int, top_k: int = 5) -> List[Dict]:
    """
    Search for chunks similar to query using vector similarity
    
    Args:
        query: User query
        meeting_id: ID of the meeting to search in
        top_k: Number of top results to return
    
    Returns:
        List of dicts with chunk text, score, and metadata
    """
    try:
        # Get query embedding
        query_embedding = get_embedding(query)
        
        # Search in Qdrant
        results = qdrant_client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_embedding,
            query_filter={
                "must": [
                    {
                        "key": "meeting_id",
                        "match": {"value": meeting_id}
                    }
                ]
            },
            limit=top_k,
            with_payload=True
        )
        
        # Format results
        formatted_results = []
        for result in results:
            formatted_results.append({
                "text": result.payload.get("text", ""),
                "score": result.score,
                "chunk_index": result.payload.get("chunk_index", 0),
                "start_time": result.payload.get("start_time"),
                "end_time": result.payload.get("end_time"),
                "metadata": result.payload
            })
        
        return formatted_results
    
    except Exception as e:
        logger.error(f"Error searching similar chunks: {str(e)}")
        return []


def delete_meeting_embeddings(meeting_id: int):
    """Delete all embeddings for a meeting"""
    try:
        qdrant_client.delete(
            collection_name=COLLECTION_NAME,
            points_selector={
                "filter": {
                    "must": [
                        {
                            "key": "meeting_id",
                            "match": {"value": meeting_id}
                        }
                    ]
                }
            }
        )
        logger.info(f"Deleted embeddings for meeting {meeting_id}")
    except Exception as e:
        logger.error(f"Error deleting embeddings: {str(e)}")
        raise
