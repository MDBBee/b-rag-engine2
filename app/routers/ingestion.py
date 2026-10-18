import json
import logging
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import StreamingResponse

from app.config import settings
from app.middleware.auth import UserInfo, get_current_user
from app.utils.file_validation import save_temp_with_limit
from app.utils.ingestion_pipeline import ingestion_pipeline_stream

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/ingest",
    tags=["ingestion"],
)

MAX_COLLECTION_NAME_LENGTH = 40


def filename_to_collection_name(filename: str) -> str:
    """Convert filename to collection name: 'My Thesis.pdf' -> 'my_thesis'"""
    name = Path(filename).stem
    name = name.lower()
    name = re.sub(r'[^a-z0-9]+', '_', name)
    name = name.strip('_')
    if not name:
        return f"doc_{uuid.uuid4().hex[:8]}"
    return name[:MAX_COLLECTION_NAME_LENGTH]


@router.post("")
async def ingest_stream(
    file: UploadFile = File(...),
    collection_name: str | None = Form(None),
    project_name: str | None = Form(None),
    chunk_size: int | None = Form(None),
    chunk_overlap: int | None = Form(None),
    text_splitter: str | None = Form(None),
    force_reprocess: bool = Form(False),
    user: UserInfo = Depends(get_current_user),
):
    """Streaming ingestion endpoint. Returns SSE events with progress updates."""
    tmp_path = await save_temp_with_limit(file, settings.max_ingest_file_size)

    if not collection_name:
        collection_name = filename_to_collection_name(file.filename)

    async def event_generator():
        try:
            if force_reprocess:
                from app.utils import mongodb
                await mongodb.delete_vectors_by_source(user.id, collection_name, file.filename)

            async for event_type, data in ingestion_pipeline_stream(
                file_path=tmp_path,
                filename=file.filename,
                collection_name=collection_name,
                user_id=user.id,
                project_name=project_name,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                text_splitter=text_splitter,
            ):
                payload = json.dumps({"type": event_type, **data})
                yield f"data: {payload}\n\n"
        except Exception:
            logger.exception("Ingestion stream failed")
            yield f"data: {json.dumps({'type': 'error', 'message': 'Ingestion failed'})}\n\n"
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
