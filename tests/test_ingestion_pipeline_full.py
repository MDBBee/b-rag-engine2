from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.utils.ingestion_pipeline import ingestion_pipeline


async def test_ingestion_pipeline_success():
    with patch("app.utils.ingestion_pipeline.check_collection_exists") as mock_check, \
         patch("app.utils.ingestion_pipeline.create_project") as mock_create_project, \
         patch("app.utils.ingestion_pipeline.MarkItDown") as mock_markitdown, \
         patch("app.utils.ingestion_pipeline.get_splitter") as mock_splitter, \
         patch("app.utils.ingestion_pipeline.mongodb") as mock_mongodb:
        
        mock_check.return_value = False
        mock_md_instance = MagicMock()
        mock_md_instance.convert.return_value.text_content = "Test content here"
        mock_markitdown.return_value = mock_md_instance
        
        mock_chunk = MagicMock()
        mock_chunk.page_content = "Test chunk"
        mock_chunk.metadata = {}
        mock_splitter_instance = MagicMock()
        mock_splitter_instance.split_text.return_value = [mock_chunk]
        mock_splitter.return_value = mock_splitter_instance
        
        mock_mongodb.embeddings.embed_documents.return_value = [[0.1, 0.2, 0.3]]
        mock_mongodb.vectors.insert_many = AsyncMock()
        
        result = await ingestion_pipeline(
            file_path="test.txt",
            filename="test.txt",
            collection_name="test-collection",
            user_id="user-123"
        )
        
        chunk_count, doc_type, page_count, chunks, summarized = result
        assert chunk_count == 1
        assert doc_type == "txt"
        assert page_count == 0
        assert len(chunks) == 1
        assert len(summarized) == 1
        mock_create_project.assert_called_once_with(
            user_id="user-123",
            name="test.txt",
            collection_name="test-collection",
            file_name="test.txt",
            chunk_count=1,
            document_type="txt",
        )


async def test_ingestion_pipeline_collection_exists():
    with patch("app.utils.ingestion_pipeline.check_collection_exists") as mock_check:
        mock_check.return_value = True
        with pytest.raises(ValueError, match="already exists"):
            await ingestion_pipeline(
                file_path="test.txt",
                filename="test.txt",
                collection_name="existing-collection",
                user_id="user-123"
            )


async def test_ingestion_pipeline_pdf_detection():
    with patch("app.utils.ingestion_pipeline.check_collection_exists") as mock_check, \
         patch("app.utils.ingestion_pipeline.create_project"), \
         patch("app.utils.ingestion_pipeline.MarkItDown") as mock_markitdown, \
         patch("app.utils.ingestion_pipeline.get_splitter") as mock_splitter, \
         patch("app.utils.ingestion_pipeline.mongodb") as mock_mongodb, \
         patch("app.utils.ingestion_pipeline.pymupdf") as mock_pymupdf:
        
        mock_check.return_value = False
        mock_md_instance = MagicMock()
        mock_md_instance.convert.return_value.text_content = "PDF content"
        mock_markitdown.return_value = mock_md_instance
        
        mock_chunk = MagicMock()
        mock_chunk.page_content = "Test chunk"
        mock_chunk.metadata = {}
        mock_splitter_instance = MagicMock()
        mock_splitter_instance.split_text.return_value = [mock_chunk]
        mock_splitter.return_value = mock_splitter_instance
        
        mock_mongodb.embeddings.embed_documents.return_value = [[0.1, 0.2]]
        mock_mongodb.vectors.insert_many = AsyncMock()
        
        mock_pages = []
        for i in range(5):
            mock_page = MagicMock()
            mock_page.get_text.return_value = f"Page {i+1} content"
            mock_pages.append(mock_page)
        
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=5)
        mock_doc.__iter__ = MagicMock(return_value=iter(mock_pages))
        mock_pymupdf.open.return_value = mock_doc
        
        result = await ingestion_pipeline(
            file_path="test.pdf",
            filename="test.pdf",
            collection_name="test-collection",
            user_id="user-123"
        )
        
        _, doc_type, page_count, _, _ = result
        assert doc_type == "pdf"
        assert page_count == 5


async def test_ingestion_pipeline_metadata_enrichment():
    with patch("app.utils.ingestion_pipeline.check_collection_exists") as mock_check, \
         patch("app.utils.ingestion_pipeline.create_project"), \
         patch("app.utils.ingestion_pipeline.MarkItDown") as mock_markitdown, \
         patch("app.utils.ingestion_pipeline.get_splitter") as mock_splitter, \
         patch("app.utils.ingestion_pipeline.mongodb") as mock_mongodb:
        
        mock_check.return_value = False
        mock_md_instance = MagicMock()
        mock_md_instance.convert.return_value.text_content = "Content"
        mock_markitdown.return_value = mock_md_instance
        
        mock_chunk = MagicMock()
        mock_chunk.page_content = "Test chunk"
        mock_chunk.metadata = {"existing": "data"}
        mock_splitter_instance = MagicMock()
        mock_splitter_instance.split_text.return_value = [mock_chunk]
        mock_splitter.return_value = mock_splitter_instance
        
        mock_mongodb.embeddings.embed_documents.return_value = [[0.1, 0.2]]
        mock_mongodb.vectors.insert_many = AsyncMock()
        
        await ingestion_pipeline(
            file_path="test.txt",
            filename="document.pdf",
            collection_name="test-collection",
            user_id="user-123"
        )
        
        assert "source" in mock_chunk.metadata
        assert mock_chunk.metadata["source"] == "document.pdf"
        assert "chunk_index" in mock_chunk.metadata
        assert "total_chunks" in mock_chunk.metadata
