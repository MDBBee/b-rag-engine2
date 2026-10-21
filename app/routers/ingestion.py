import json
import logging
import re
import uuid
from collections.abc import AsyncIterable
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.config import settings
from app.limiter import limiter
from app.middleware.auth import UserInfo, get_current_user
from app.utils.file_validation import save_temp_with_limit
from app.utils.ingestion_pipeline import ingestion_pipeline_stream

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/ingest",
    tags=["ingestion"],
)

MAX_PROJECT_NAME_LENGTH = 40


def filename_to_project_name(filename: str) -> str:
    """Convert filename to project name: 'My Thesis.pdf' -> 'my_thesis'"""
    name = Path(filename).stem
    name = name.lower()
    name = re.sub(r'[^a-z0-9]+', '_', name)
    name = name.strip('_')
    if not name:
        return f"doc_{uuid.uuid4().hex[:8]}"
    return name[:MAX_PROJECT_NAME_LENGTH]


@router.post("", response_class=EventSourceResponse)
@limiter.limit("5/minute")
async def ingest_stream(
    request: Request,
    file: UploadFile = File(...),
    project_name: str | None = Form(None),
    chunk_size: int | None = Form(None),
    chunk_overlap: int | None = Form(None),
    text_splitter: str | None = Form(None),
    embedding_model: str | None = Form(None),
    force_reprocess: bool = Form(False),
    use_ocr: bool = Form(False),
    user: UserInfo = Depends(get_current_user),
) -> AsyncIterable[ServerSentEvent]:
    """Streaming ingestion endpoint. Returns SSE events with progress updates."""
    if use_ocr and user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required for OCR")

    tmp_path = await save_temp_with_limit(file, settings.max_ingest_file_size)

    if not project_name:
        project_name = filename_to_project_name(file.filename)

    try:
        if force_reprocess:
            from app.utils import mongodb
            await mongodb.delete_vectors_by_source(user.id, project_name, file.filename)

        async for event_type, data in ingestion_pipeline_stream(
            file_path=tmp_path,
            filename=file.filename,
            project_name=project_name,
            user_id=user.id,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            text_splitter=text_splitter,
            embedding_model=embedding_model,
            use_ocr=use_ocr,
        ):
            payload = json.dumps({"type": event_type, **data})
            yield ServerSentEvent(raw_data=payload)
    except Exception:
        logger.exception("Ingestion stream failed")
        yield ServerSentEvent(raw_data=json.dumps({"type": "error", "message": "Ingestion failed"}))
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except PermissionError:
            logger.warning(f"Could not delete temp file {tmp_path} - still in use by OCR thread. File will be cleaned up by OS.")
