import re
import uuid
import asyncio
import tempfile
import logging
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends

from app.utils.ingestion_pipeline import ingestion_pipeline
from app.typing.schemas import IngestResponse
from app.middleware.auth import get_current_user, UserInfo

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_FILE_SIZE = 50 * 1024 * 1024
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


@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    file: UploadFile = File(...),
    collection_name: str | None = Form(None),
    embedding_model: str | None = Form(None),
    chunk_size: int | None = Form(None),
    chunk_overlap: int | None = Form(None),
    user: UserInfo = Depends(get_current_user),
):
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large. Max size: {MAX_FILE_SIZE // (1024*1024)}MB")

    if not collection_name:
        collection_name = filename_to_collection_name(file.filename)

    suffix = Path(file.filename).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        chunk_count, document_type, no_of_pages, chunks, summarized_chunks = await ingestion_pipeline(
            tmp_path, file.filename, collection_name, user.id,
            embedding_model=embedding_model,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        return IngestResponse(
            status="ok",
            chunk_count=chunk_count,
            document_type=document_type,
            no_of_pages=no_of_pages,
            chunks=chunks,
            summarized_chunks=summarized_chunks,
        )
    except ValueError as e:
        logger.warning(f"Collection uniqueness violation: {e}")
        raise HTTPException(status_code=409, detail=str(e))
    except asyncio.TimeoutError:
        logger.error("Ingestion timed out")
        raise HTTPException(status_code=504, detail="Ingestion timed out. Please try again.")
    except Exception as e:
        logger.error(f"Ingestion failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ingestion failed. Please try again.")
    finally:
        Path(tmp_path).unlink(missing_ok=True)
