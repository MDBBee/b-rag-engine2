from unittest.mock import ANY, AsyncMock, MagicMock, patch

from app.utils.ingestion_pipeline import ingestion_pipeline


async def test_ingestion_pipeline_success():
    with patch("app.utils.ingestion_pipeline.mongodb") as mock_mongodb, \
         patch("app.utils.ingestion_pipeline.create_project") as mock_create_project, \
         patch("app.utils.ingestion_pipeline.MarkItDown") as mock_markitdown, \
         patch("app.utils.ingestion_pipeline.get_splitter") as mock_splitter:
        
        mock_mongodb.vectors.count_documents = AsyncMock(return_value=0)
        mock_mongodb.projects.find_one = AsyncMock(return_value=None)
        
        # Mock get_embeddings to return a mock embeddings instance
        mock_embeddings = MagicMock()
        mock_embeddings.embed_documents.return_value = [[0.1, 0.2, 0.3]]
        mock_mongodb.get_embeddings.return_value = mock_embeddings
        
        mock_md_instance = MagicMock()
        mock_md_instance.convert.return_value.text_content = "Test content here"
        mock_markitdown.return_value = mock_md_instance
        
        mock_chunk = MagicMock()
        mock_chunk.page_content = "Test chunk"
        mock_chunk.metadata = {}
        mock_splitter_instance = MagicMock()
        mock_splitter_instance.split_text.return_value = [mock_chunk]
        mock_splitter.return_value = mock_splitter_instance
        
        mock_mongodb.vectors.insert_many = AsyncMock()
        
        result = await ingestion_pipeline(
            file_path="test.txt",
            filename="test.txt",
            project_name="test-collection",
            user_id="user-123"
        )
        
        chunk_count, doc_type, page_count, first_chunk_index, chunks, summarized = result
        assert chunk_count == 1
        assert doc_type == "txt"
        assert page_count == 0
        assert first_chunk_index == 0
        assert len(chunks) == 1
        assert len(summarized) == 1
        mock_create_project.assert_called_once_with(
            user_id="user-123",
            name="test-collection",
            project_name="test-collection",
            documents=[{
                "name": "test.txt",
                "type": "txt",
                "chunk_count": 1,
                "token_count": ANY,
                "embedding_model": "text-embedding-3-small",
                "uploaded_at": mock_create_project.call_args.kwargs["documents"][0]["uploaded_at"],
            }],
            chunk_count=1,
        )


async def test_ingestion_pipeline_append():
    """Test that appending to existing collection updates chunk indices and project."""
    with patch("app.utils.ingestion_pipeline.mongodb") as mock_mongodb, \
         patch("app.utils.ingestion_pipeline.MarkItDown") as mock_markitdown, \
         patch("app.utils.ingestion_pipeline.get_splitter") as mock_splitter:
        
        # Simulate existing collection with 5 chunks
        mock_mongodb.vectors.count_documents = AsyncMock(return_value=5)
        mock_mongodb.projects.find_one = AsyncMock(return_value={
            "user_id": "user-123",
            "project_name": "test-collection",
            "documents": [{"name": "chapter1.txt", "type": "txt", "chunk_count": 5}],
            "chunk_count": 5,
        })
        mock_mongodb.projects.update_one = AsyncMock()
        
        # Mock get_embeddings to return a mock embeddings instance
        mock_embeddings = MagicMock()
        mock_embeddings.embed_documents.return_value = [[0.1, 0.2, 0.3]]
        mock_mongodb.get_embeddings.return_value = mock_embeddings
        
        mock_md_instance = MagicMock()
        mock_md_instance.convert.return_value.text_content = "Chapter 2 content"
        mock_markitdown.return_value = mock_md_instance
        
        mock_chunk = MagicMock()
        mock_chunk.page_content = "New chunk"
        mock_chunk.metadata = {}
        mock_splitter_instance = MagicMock()
        mock_splitter_instance.split_text.return_value = [mock_chunk]
        mock_splitter.return_value = mock_splitter_instance
        
        mock_mongodb.vectors.insert_many = AsyncMock()
        
        result = await ingestion_pipeline(
            file_path="chapter2.txt",
            filename="chapter2.txt",
            project_name="test-collection",
            user_id="user-123"
        )
        
        chunk_count, *_ = result
        assert chunk_count == 1
        
        # Verify chunk index starts from existing count
        assert mock_chunk.metadata["chunk_index"] == 5
        assert mock_chunk.metadata["total_chunks"] == 6
        
        # Verify project was updated (not created)
        mock_mongodb.projects.update_one.assert_called_once()
        update_filter, update_ops = mock_mongodb.projects.update_one.call_args[0]
        assert update_filter == {"user_id": "user-123", "project_name": "test-collection"}
        assert update_ops["$set"]["chunk_count"] == 6
        assert "$push" in update_ops
        assert update_ops["$push"]["documents"]["name"] == "chapter2.txt"


async def test_ingestion_pipeline_pdf_detection():
    with patch("app.utils.ingestion_pipeline.mongodb") as mock_mongodb, \
         patch("app.utils.ingestion_pipeline.create_project"), \
         patch("app.utils.ingestion_pipeline.MarkItDown") as mock_markitdown, \
         patch("app.utils.ingestion_pipeline.get_splitter") as mock_splitter, \
         patch("app.utils.ingestion_pipeline.pymupdf") as mock_pymupdf:
        
        mock_mongodb.vectors.count_documents = AsyncMock(return_value=0)
        mock_mongodb.projects.find_one = AsyncMock(return_value=None)
        
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
            project_name="test-collection",
            user_id="user-123"
        )
        
        _, doc_type, page_count, _, _, _ = result
        assert doc_type == "pdf"
        assert page_count == 5


async def test_ingestion_pipeline_metadata_enrichment():
    with patch("app.utils.ingestion_pipeline.mongodb") as mock_mongodb, \
         patch("app.utils.ingestion_pipeline.create_project"), \
         patch("app.utils.ingestion_pipeline.MarkItDown") as mock_markitdown, \
         patch("app.utils.ingestion_pipeline.get_splitter") as mock_splitter:
        
        mock_mongodb.vectors.count_documents = AsyncMock(return_value=0)
        mock_mongodb.projects.find_one = AsyncMock(return_value=None)
        
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
            project_name="test-collection",
            user_id="user-123"
        )
        
        assert "source" in mock_chunk.metadata
        assert mock_chunk.metadata["source"] == "document.pdf"
        assert "chunk_index" in mock_chunk.metadata
        assert "total_chunks" in mock_chunk.metadata
