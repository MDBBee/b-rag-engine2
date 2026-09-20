import re
import uuid
import tempfile
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from app.utils.ingestion_pipeline import ingest_document
from app.typing.schemas import IngestResponse

router = APIRouter()

MAX_FILE_SIZE = 50 * 1024 * 1024
MAX_COLLECTION_NAME_LENGTH = 40


def filename_to_collection_name(filename: str) -> str:
    """Convert filename to collection name: 'My Thesis.pdf' -> 'my_thesis'"""
    name = Path(filename).stem  # remove extension
    name = name.lower()
    name = re.sub(r'[^a-z0-9]+', '_', name)  # non-alphanumeric → underscore
    name = name.strip('_')
    if not name:
        return f"doc_{uuid.uuid4().hex[:8]}"
    return name[:MAX_COLLECTION_NAME_LENGTH]


@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    file: UploadFile = File(...),
    collection_name: str | None = Form(None),
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
        chunk_count = await ingest_document(tmp_path, file.filename, collection_name)
        return IngestResponse(
            status="ok",
            chunk_count=chunk_count,
            collection_name=collection_name,
            chunks=[],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        Path(tmp_path).unlink(missing_ok=True)
