import pytest
from fastapi import HTTPException

from app.utils.file_validation import MIME_MAP, validate_filename


def test_validate_filename_single_extension():
    validate_filename("document.pdf")


def test_validate_filename_no_extension():
    validate_filename("README")


def test_validate_filename_double_extension():
    with pytest.raises(HTTPException) as exc_info:
        validate_filename("evil.exe.pdf")
    assert exc_info.value.status_code == 400


def test_validate_filename_multiple_extensions():
    with pytest.raises(HTTPException) as exc_info:
        validate_filename("file.tar.gz.pdf")
    assert exc_info.value.status_code == 400


def test_mime_map_has_common_types():
    assert ".pdf" in MIME_MAP
    assert ".png" in MIME_MAP
    assert ".jpg" in MIME_MAP
    assert ".docx" in MIME_MAP
    assert MIME_MAP[".pdf"] == "application/pdf"
