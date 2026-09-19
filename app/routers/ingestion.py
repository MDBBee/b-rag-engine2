import tempfile
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from app.utils.ingestion_pipeline import ingest_document
from app.typing.schemas import IngestResponse

router = APIRouter()


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
        tmp.write(content)
        tmp_path = tmp.name

    try:
        chunk_count = ingest_document(tmp_path, file.filename, collection_name)
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
