import logging
from io import BytesIO
from pathlib import Path

import fitz
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.config import settings
from app.middleware.auth import get_current_user
from app.utils.conversion_utils import (
    DOCX_EXTENSIONS,
    IMAGE_EXTENSIONS,
    PDF_EXTENSIONS,
    count_pdf_pages,
    docx_to_pdf,
    docx_to_pdf_via_mammoth,
    image_to_pdf,
)
from app.utils.file_validation import save_temp_with_limit

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/process_files",
    tags=["file_processing"],
    dependencies=[Depends(get_current_user)],
)

SUPPORTED = PDF_EXTENSIONS | IMAGE_EXTENSIONS | DOCX_EXTENSIONS


def convert_to_pdf(file_path: str) -> bytes:
    ext = Path(file_path).suffix.lower()

    if ext in PDF_EXTENSIONS:
        with open(file_path, "rb") as f:
            return f.read()

    if ext in IMAGE_EXTENSIONS:
        pdf_bytes, _ = image_to_pdf(file_path)
        return pdf_bytes

    if ext in DOCX_EXTENSIONS:
        try:
            pdf_bytes, _ = docx_to_pdf(file_path)
            return pdf_bytes
        except Exception:
            pdf_bytes, _ = docx_to_pdf_via_mammoth(file_path)
            return pdf_bytes

    raise ValueError(f"Unsupported file type: {ext}")


@router.post("/merge")
async def process_files(files: list[UploadFile] = File(...)):
    """Single file converts to PDF, multiple files merge into one PDF."""
    if not files:
        raise HTTPException(status_code=400, detail="At least 1 file required")

    tmp_paths: list[str] = []
    try:
        for file in files:
            ext = Path(file.filename or "").suffix.lower()
            if ext not in SUPPORTED:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED))}",
                )
            tmp_path = await save_temp_with_limit(file, settings.max_processing_file_size)
            tmp_paths.append(tmp_path)

        pdf_parts = [convert_to_pdf(p) for p in tmp_paths]

        if len(pdf_parts) == 1:
            pdf_bytes = pdf_parts[0]
            headers = {"X-Pages": str(count_pdf_pages(pdf_bytes))}
        else:
            merger = fitz.open()
            for pdf_bytes in pdf_parts:
                doc = fitz.open("pdf", pdf_bytes)
                merger.insert_pdf(doc)
                doc.close()
            output = BytesIO()
            merger.save(output)
            merger.close()
            output.seek(0)
            pdf_bytes = output.read()
            headers = {
                "X-Total-Pages": str(count_pdf_pages(pdf_bytes)),
                "X-File-Count": str(len(files)),
            }

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="merged.pdf"', **headers},
        )

    except HTTPException:
        raise
    except Exception:
        logger.exception("File processing failed for %d files", len(files))
        raise HTTPException(status_code=500, detail="File processing failed")
    finally:
        for tmp_path in tmp_paths:
            Path(tmp_path).unlink(missing_ok=True)
