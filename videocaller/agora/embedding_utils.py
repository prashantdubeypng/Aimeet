"""LangChain embeddings and Qdrant vector DB management"""
import logging
import uuid
from typing import List, Dict
from django.conf import settings
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, Filter, FieldCondition, MatchValue, PayloadSchemaType
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_qdrant import QdrantVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)

qdrant_client = QdrantClient(url=settings.QDRANT_URL, api_key=getattr(settings, 'QDRANT_API_KEY', None))

EMBEDDING_MODEL = getattr(settings, 'HF_EMBEDDING_MODEL', 'sentence-transformers/all-MiniLM-L6-v2')
EMBEDDING_DIMENSION = getattr(settings, 'HF_EMBEDDING_DIMENSION', None)
COLLECTION_NAME = getattr(settings, 'QDRANT_COLLECTION_NAME', 'meeting_transcripts')
_embeddings = None


def get_embeddings() -> HuggingFaceEmbeddings:
    """Lazily initialize embeddings to reduce startup memory usage."""
    global _embeddings
    if _embeddings is None:
        _embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            model_kwargs={"device": "cpu"},
        )
    return _embeddings


def get_embedding_dimension() -> int:
    """Get embedding dimension from config or derive it from the model."""
    if EMBEDDING_DIMENSION:
        return int(EMBEDDING_DIMENSION)

    embeddings = get_embeddings()
    client = getattr(embeddings, "client", None)
    if client and hasattr(client, "get_sentence_embedding_dimension"):
        return int(client.get_sentence_embedding_dimension())

    raise ValueError("HF_EMBEDDING_DIMENSION is not set and model dimension is unavailable")


def ensure_collection_exists():
    """Create Qdrant collection if it doesn't exist"""
    try:
        collection = qdrant_client.get_collection(COLLECTION_NAME)
        existing_size = collection.config.params.vectors.size
        desired_size = get_embedding_dimension()
        if existing_size != desired_size:
            logger.warning(
                "Qdrant collection size mismatch (%s != %s), recreating: %s",
                existing_size,
                desired_size,
                COLLECTION_NAME
            )
            qdrant_client.delete_collection(COLLECTION_NAME)
            qdrant_client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=desired_size, distance=Distance.COSINE),
            )
    except Exception:
        logger.info(f"Creating Qdrant collection: {COLLECTION_NAME}")
        desired_size = get_embedding_dimension()
        qdrant_client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=desired_size, distance=Distance.COSINE),
        )

    ensure_payload_indexes()


def ensure_payload_indexes() -> None:
    """Ensure payload indexes exist for filtered searches."""
    try:
        qdrant_client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="meeting_id",
            field_schema=PayloadSchemaType.INTEGER,
        )
    except Exception as e:
        logger.info("Skipping payload index creation for meeting_id: %s", str(e))


def chunk_transcript(transcript_text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """
    Split transcript into overlapping chunks using RecursiveCharacterTextSplitter
    
    Args:
        transcript_text: Full transcript text
        chunk_size: Target tokens per chunk (approximate)
        overlap: Token overlap between chunks
    
    Returns:
        List of text chunks
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", ". ", " ", ""]
    )
    logger.info(splitter.split_text(transcript_text))
    return splitter.split_text(transcript_text)


def get_vectorstore() -> QdrantVectorStore:
    ensure_collection_exists()
    return QdrantVectorStore(
        client=qdrant_client,
        collection_name=COLLECTION_NAME,
        embedding=get_embeddings(),
    )


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
        from .models import MeetingRoom

        vectorstore = get_vectorstore()
        meeting_title = MeetingRoom.objects.filter(id=meeting_id).values_list("title", flat=True).first() or ""
        vector_ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, f"meeting:{meeting_id}:{idx}")) for idx in range(len(chunks))]

        metadatas = []
        logger.info("inside the store_chunk_in_vector")
        logger.info(chunks)
        for idx, chunk in enumerate(chunks):
            payload = {
                "meeting_id": meeting_id,
                "meeting_title": meeting_title,
                "chunk_index": idx,
                "text": chunk[:512],
                "chunk_length": len(chunk),
                "source_type": "meeting_transcript"
            }

            if chunk_objects and idx < len(chunk_objects):
                payload["chunk_db_id"] = chunk_objects[idx].id
                if chunk_objects[idx].start_time:
                    payload["start_time"] = chunk_objects[idx].start_time
                if chunk_objects[idx].end_time:
                    payload["end_time"] = chunk_objects[idx].end_time

            metadatas.append(payload)

        vectorstore.add_texts(texts=chunks, metadatas=metadatas, ids=vector_ids)
        logger.info(f"Stored {len(chunks)} chunks for meeting {meeting_id}")
        return vector_ids
    except Exception as e:
        logger.error(f"Error storing chunks in vector DB: {str(e)}")
        raise


def store_document_chunks_in_vector_db(
    meeting_id: int,
    document,
    chunks: List[str],
    chunk_objects: List = None
) -> List[str]:
    """Store document chunks and their embeddings in Qdrant"""
    ensure_collection_exists()

    try:
        from .models import MeetingRoom

        vectorstore = get_vectorstore()
        meeting_title = MeetingRoom.objects.filter(id=meeting_id).values_list("title", flat=True).first() or ""
        vector_ids = [str(uuid.uuid5(uuid.NAMESPACE_URL, f"document:{document.id}:{idx}")) for idx in range(len(chunks))]

        metadatas = []
        logger.info(chunks)
        for idx, chunk in enumerate(chunks):
            payload = {
                "meeting_id": meeting_id,
                "meeting_title": meeting_title,
                "document_id": document.id,
                "document_name": document.file_name,
                "chunk_index": idx,
                "text": chunk[:512],
                "chunk_length": len(chunk),
                "source_type": "document"
            }

            if chunk_objects and idx < len(chunk_objects):
                payload["chunk_db_id"] = chunk_objects[idx].id
                payload["block_type"] = chunk_objects[idx].block_type

            metadatas.append(payload)

        vectorstore.add_texts(texts=chunks, metadatas=metadatas, ids=vector_ids)
        logger.info(f"Stored {len(chunks)} document chunks for meeting {meeting_id}")
        return vector_ids
    except Exception as e:
        logger.error(f"Error storing document chunks in vector DB: {str(e)}")
        raise


def search_similar_chunks(query: str, meeting_id: int | None = None, top_k: int = 5) -> List[Dict]:
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
        print("trying to search the similiar to the query asked")
        vectorstore = get_vectorstore()
        filter_ = None
        if meeting_id is not None:
            filter_ = Filter(
                must=[FieldCondition(key="meeting_id", match=MatchValue(value=meeting_id))]
            )

        results = vectorstore.similarity_search_with_score(query, k=top_k, filter=filter_)
        formatted_results = []
        for doc, score in results:
            metadata = doc.metadata or {}
            formatted_results.append({
                "text": doc.page_content,
                "score": score,
                "chunk_index": metadata.get("chunk_index", 0),
                "start_time": metadata.get("start_time"),
                "end_time": metadata.get("end_time"),
                "source_type": metadata.get("source_type", "meeting_transcript"),
                "meeting_title": metadata.get("meeting_title"),
                "document_id": metadata.get("document_id"),
                "document_name": metadata.get("document_name"),
                "metadata": metadata
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
