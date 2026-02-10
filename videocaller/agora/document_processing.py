"""Document processing strategies for external uploads."""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from django.conf import settings
from django.utils import timezone

from .assemblyai_utils import AssemblyAIClient
from .embedding_utils import chunk_transcript, store_document_chunks_in_vector_db
from .models import DocumentUpload, DocumentChunk
from .recording_utils import S3Manager


ALLOWED_EXTENSIONS = {".pdf", ".txt", ".doc", ".docx", ".mp3"}


class BaseDocumentStrategy(ABC):
    """Base strategy for processing an uploaded file."""

    @abstractmethod
    def process(self, document: DocumentUpload, local_path: str, s3_url: Optional[str], presigned_url: Optional[str]) -> Dict:
        """Process a document and store chunks + embeddings."""
        raise NotImplementedError

    def _store_chunks(self, document: DocumentUpload, chunks: List[str], block_types: Optional[List[str]] = None,
                      metadatas: Optional[List[Dict]] = None) -> int:
        chunk_objects = []
        for idx, chunk_text in enumerate(chunks):
            block_type = block_types[idx] if block_types and idx < len(block_types) else "text"
            metadata = metadatas[idx] if metadatas and idx < len(metadatas) else {}
            chunk_objects.append(
                DocumentChunk.objects.create(
                    document=document,
                    chunk_text=chunk_text,
                    chunk_index=idx,
                    block_type=block_type,
                    metadata=metadata,
                )
            )

        store_document_chunks_in_vector_db(document.meeting_id, document, chunks, chunk_objects)
        document.embeddings_created_at = timezone.now()
        document.save(update_fields=["embeddings_created_at"])
        return len(chunks)


class AudioDocumentStrategy(BaseDocumentStrategy):
    """Process audio files by transcribing and chunking text."""

    def process(self, document: DocumentUpload, local_path: str, s3_url: Optional[str], presigned_url: Optional[str]) -> Dict:
        if not settings.ASSEMBLYAI_API_KEY:
            raise RuntimeError("AssemblyAI API key is not configured")

        audio_url = presigned_url or s3_url
        if not audio_url:
            raise RuntimeError("Audio requires S3 upload or presigned URL for transcription")

        assembly_client = AssemblyAIClient()
        start_data = assembly_client.start_transcription(audio_url)
        transcript_id = start_data.get("id")
        status = start_data.get("status", "processing")

        transcript_text = None
        if transcript_id:
            result = assembly_client.wait_for_transcription(transcript_id, timeout_seconds=120, poll_interval=4)
            status = result.get("status", status)
            if status == "completed":
                transcript_text = result.get("text")

        if status != "completed" or not transcript_text:
            error_msg = result.get("error") if transcript_id else "Transcription failed"
            raise RuntimeError(error_msg or "Transcription failed")

        document.raw_text = transcript_text
        document.status = "processing"
        document.save(update_fields=["raw_text", "status"])

        chunks = chunk_transcript(transcript_text)
        chunk_count = self._store_chunks(document, chunks)
        return {"chunk_count": chunk_count, "status": "completed"}


class TextDocumentStrategy(BaseDocumentStrategy):
    """Process plain text files."""

    def process(self, document: DocumentUpload, local_path: str, s3_url: Optional[str], presigned_url: Optional[str]) -> Dict:
        with open(local_path, "r", encoding="utf-8", errors="ignore") as handle:
            raw_text = handle.read()

        if not raw_text.strip():
            raise RuntimeError("Empty text file")

        document.raw_text = raw_text
        document.status = "processing"
        document.save(update_fields=["raw_text", "status"])

        chunks = chunk_transcript(raw_text)
        chunk_count = self._store_chunks(document, chunks)
        return {"chunk_count": chunk_count, "status": "completed"}


class UnstructuredDocumentStrategy(BaseDocumentStrategy):
    """Process PDF/DOC/DOCX with unstructured partitioning."""

    def process(self, document: DocumentUpload, local_path: str, s3_url: Optional[str], presigned_url: Optional[str]) -> Dict:
        try:
            from unstructured.partition.auto import partition
        except Exception as exc:
            raise RuntimeError("unstructured library is required for PDF/DOC processing") from exc

        elements = partition(filename=local_path)
        blocks: List[str] = []
        block_types: List[str] = []
        metadatas: List[Dict] = []

        for element in elements:
            text = getattr(element, "text", "") or ""
            if not text.strip():
                continue
            block_type = getattr(element, "category", None) or element.__class__.__name__
            metadata_obj = getattr(element, "metadata", None)
            metadata = metadata_obj.to_dict() if metadata_obj and hasattr(metadata_obj, "to_dict") else {}
            blocks.append(text.strip())
            block_types.append(str(block_type).lower())
            metadatas.append(metadata)

        if not blocks:
            raise RuntimeError("No readable content extracted from document")

        raw_text = "\n\n".join(blocks)
        document.raw_text = raw_text
        document.status = "processing"
        document.save(update_fields=["raw_text", "status"])

        chunks: List[str] = []
        chunk_block_types: List[str] = []
        chunk_metadatas: List[Dict] = []

        for block_text, block_type, metadata in zip(blocks, block_types, metadatas):
            block_chunks = chunk_transcript(block_text)
            for chunk in block_chunks:
                chunks.append(chunk)
                chunk_block_types.append(block_type)
                chunk_metadatas.append(metadata)

        chunk_count = self._store_chunks(document, chunks, chunk_block_types, chunk_metadatas)
        return {"chunk_count": chunk_count, "status": "completed"}


class DocumentProcessorFactory:
    """Factory to select processing strategy based on extension."""

    @staticmethod
    def get_strategy(file_path: str) -> BaseDocumentStrategy:
        _, ext = os.path.splitext(file_path.lower())
        if ext not in ALLOWED_EXTENSIONS:
            raise RuntimeError(f"Unsupported file type: {ext}")

        if ext == ".mp3":
            return AudioDocumentStrategy()
        if ext == ".txt":
            return TextDocumentStrategy()
        return UnstructuredDocumentStrategy()

    @staticmethod
    def upload_to_s3_if_configured(local_path: str, s3_key: str) -> Dict:
        s3_url = None
        presigned_url = None
        s3_error = None
        if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY and settings.AWS_STORAGE_BUCKET_NAME:
            try:
                s3_manager = S3Manager()
                uploaded = s3_manager.upload_file(local_path, s3_key)
                if uploaded:
                    s3_url = s3_manager.get_s3_url(s3_key)
                    presigned_url = s3_manager.generate_presigned_url(s3_key)
                else:
                    s3_error = "S3 upload failed"
            except Exception as upload_error:
                s3_error = str(upload_error)
        return {
            "s3_url": s3_url,
            "presigned_url": presigned_url,
            "s3_error": s3_error
        }
