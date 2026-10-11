from app.routers.ingestion import filename_to_collection_name


def test_filename_to_collection_name_normal():
    assert filename_to_collection_name("My Thesis.pdf") == "my_thesis"


def test_filename_to_collection_name_special_chars():
    assert filename_to_collection_name("Document (2024) - Final.docx") == "document_2024_final"


def test_filename_to_collection_name_numbers():
    assert filename_to_collection_name("Report 123.pdf") == "report_123"


def test_filename_to_collection_name_empty_stem():
    result = filename_to_collection_name("...pdf")
    assert result.startswith("doc_")
    assert len(result) == 12


def test_filename_to_collection_name_long_name():
    long_name = "a" * 100 + ".pdf"
    result = filename_to_collection_name(long_name)
    assert len(result) == 40


def test_filename_to_collection_name_unicode():
    result = filename_to_collection_name("文档.pdf")
    assert result.startswith("doc_")
