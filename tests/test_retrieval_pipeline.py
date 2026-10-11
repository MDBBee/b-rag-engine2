from app.utils.retrieval_pipeline import check_metadata_query


def test_check_metadata_query_file_name():
    result = check_metadata_query(
        "what is the file name",
        file_name="document.pdf",
        project_name="my-project",
        collection_name="collection"
    )
    assert result == "The file name is document.pdf."


def test_check_metadata_query_project_name():
    result = check_metadata_query(
        "what project is this",
        file_name="document.pdf",
        project_name="my-project",
        collection_name="collection"
    )
    assert result == "The project name is my-project."


def test_check_metadata_query_collection_name():
    result = check_metadata_query(
        "what is the collection name",
        file_name="document.pdf",
        project_name="my-project",
        collection_name="my-collection"
    )
    assert result == "The collection name is my-collection."


def test_check_metadata_query_no_match():
    result = check_metadata_query(
        "what is machine learning",
        file_name="document.pdf",
        project_name="my-project",
        collection_name="collection"
    )
    assert result is None


def test_check_metadata_query_pattern_variations():
    result = check_metadata_query(
        "what's the doc name?",
        file_name="test.pdf",
        project_name="",
        collection_name=""
    )
    assert result == "The file name is test.pdf."


def test_check_metadata_query_empty_values():
    result = check_metadata_query(
        "what is the file name",
        file_name="",
        project_name="",
        collection_name=""
    )
    assert result is None
