import logging
import tempfile
from pathlib import Path

import filetype
from fastapi import HTTPException, UploadFile

logger = logging.getLogger(__name__)

MIME_MAP = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".webp": "image/webp",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def validate_filename(filename: str) -> None:
    """Reject filenames with multiple extensions (e.g., evil.exe.pdf)."""
    parts = filename.split(".")
    if len(parts) > 2:
        logger.warning("Rejected filename with multiple extensions: %s", filename)
        raise HTTPException(status_code=400, detail="Invalid file")


def validate_magic_number(file_path: str, ext: str) -> None:
    """Verify file content matches its extension using magic bytes."""
    expected_mime = MIME_MAP.get(ext)
    if not expected_mime:
        return

    kind = filetype.guess(file_path)
    if not kind:
        logger.warning("Cannot determine file type for: %s", file_path)
        raise HTTPException(status_code=400, detail="Invalid file")

    if kind.mime != expected_mime:
        logger.warning(
            "Magic number mismatch for %s: expected %s, got %s",
            file_path, expected_mime, kind.mime,
        )
        raise HTTPException(status_code=400, detail="Invalid file")


async def save_temp_with_limit(file: UploadFile, max_size: int) -> str:
    """Save upload to temp file, enforcing size limit incrementally."""
    filename = file.filename or "unknown"
    ext = Path(filename).suffix.lower()

    validate_filename(filename)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)  # noqa: SIM115
    total_size = 0

    try:
        while True:
            chunk = await file.read(8192)
            if not chunk:
                break
            total_size += len(chunk)
            if total_size > max_size:
                tmp.close()
                Path(tmp.name).unlink(missing_ok=True)
                logger.warning("File size limit exceeded: %s (%d bytes)", filename, total_size)
                raise HTTPException(status_code=413, detail="File too large")
            tmp.write(chunk)

        tmp.close()
        validate_magic_number(tmp.name, ext)
        return tmp.name

    except Exception:
        Path(tmp.name).unlink(missing_ok=True)
        logger.exception("Failed to save temp file: %s", filename)
        raise HTTPException(status_code=400, detail="Invalid file")
