import tempfile
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from app.utils.ingestion_pipeline import ingest_document
from app.typing.schemas import IngestResponse

router = APIRouter()

MAX_FILE_SIZE = 50 * 1024 * 1024


@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    file: UploadFile = File(...),
    collection_name: str = Form(...),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    suffix = Path(file.filename).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            Path(tmp.name).unlink(missing_ok=True)
            raise HTTPException(status_code=413, detail=f"File too large. Max size: {MAX_FILE_SIZE // (1024*1024)}MB")
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
