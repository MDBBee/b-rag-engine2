from app.utils.ingestion_pipeline import detect_document_type, get_page_count


def test_detect_document_type_pdf():
    assert detect_document_type("file.pdf") == "pdf"


def test_detect_document_type_docx():
    assert detect_document_type("document.docx") == "docx"


def test_detect_document_type_html():
    assert detect_document_type("page.html") == "html"


def test_detect_document_type_htm():
    assert detect_document_type("page.htm") == "html"


def test_detect_document_type_txt():
    assert detect_document_type("notes.txt") == "txt"


def test_detect_document_type_no_extension():
    assert detect_document_type("README") == "txt"


def test_get_page_count_non_pdf():
    assert get_page_count("document.docx") == 0


def test_get_page_count_txt():
    assert get_page_count("notes.txt") == 0
