import logging
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.config import settings
from app.middleware.auth import UserInfo, get_current_user
from app.typing.schemas import IngestResponse
from app.utils.file_validation import save_temp_with_limit
from app.utils.ingestion_pipeline import ingestion_pipeline

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


@router.post("", response_model=IngestResponse)
async def ingest(
    file: UploadFile = File(...),
    collection_name: str | None = Form(None),
    chunk_size: int | None = Form(None),
    chunk_overlap: int | None = Form(None),
    text_splitter: str | None = Form(None),
    user: UserInfo = Depends(get_current_user),
):
    tmp_path = await save_temp_with_limit(file, settings.max_ingest_file_size)

    if not collection_name:
        collection_name = filename_to_collection_name(file.filename)

    try:
        chunk_count, document_type, no_of_pages, chunks, summarized_chunks = await ingestion_pipeline(
            tmp_path, file.filename, collection_name, user.id,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            text_splitter=text_splitter,
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
        logger.warning("Collection uniqueness violation: %s", e)
        raise HTTPException(status_code=409, detail=str(e))
    except TimeoutError:
        logger.error("Ingestion timed out")
        raise HTTPException(status_code=504, detail="Ingestion timed out. Please try again.")
    except Exception:
        logger.exception("Ingestion failed")
        raise HTTPException(status_code=500, detail="Ingestion failed. Please try again.")
    finally:
        Path(tmp_path).unlink(missing_ok=True)
