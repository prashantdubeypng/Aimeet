"""Background tasks for document processing."""
from __future__ import annotations

import logging
import traceback

from django.core.files.storage import default_storage
from django.utils import timezone

from .document_processing import DocumentProcessorFactory
from .models import DocumentUpload

logger = logging.getLogger(__name__)


def process_document_upload(document_id: int) -> None:
    try:
        document = DocumentUpload.objects.get(id=document_id)
    except DocumentUpload.DoesNotExist:
        logger.error("Document upload %s not found", document_id)
        return

    logger.info("Starting document processing: id=%s name=%s", document.id, document.file_name)
    document.status = "processing"
    document.error_message = None
    document.save(update_fields=["status", "error_message"])

    try:
        full_path = default_storage.path(document.storage_path)
        s3_key = f"documents/{document.storage_path.split('/')[-1]}"
        s3_result = DocumentProcessorFactory.upload_to_s3_if_configured(full_path, s3_key)

        if s3_result.get("s3_url"):
            document.s3_url = s3_result["s3_url"]
            document.save(update_fields=["s3_url"])

        strategy = DocumentProcessorFactory.get_strategy(full_path)
        result = strategy.process(
            document=document,
            local_path=full_path,
            s3_url=s3_result.get("s3_url"),
            presigned_url=s3_result.get("presigned_url")
        )

        document.status = "completed"
        document.chunk_count = int(result.get("chunk_count", 0) or 0)
        document.processed_at = timezone.now()
        document.save(update_fields=["status", "processed_at", "chunk_count"])
        logger.info(
            "Completed document processing: id=%s status=%s chunks=%s",
            document.id,
            document.status,
            document.chunk_count
        )

    except Exception as exc:
        logger.error("Document processing failed: %s", exc)
        logger.error(traceback.format_exc())
        document.status = "failed"
        document.error_message = str(exc)
        document.save(update_fields=["status", "error_message"])
