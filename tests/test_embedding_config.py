"""Test embedding model configuration for OpenRouter compatibility."""
import pytest
from unittest.mock import patch, MagicMock
from app.utils import mongodb
from app.config import settings


@patch("app.utils.mongodb.OpenAIEmbeddings")
def test_openai_embedding_model_uses_default_settings(mock_openai_embeddings):
    """Test that OpenAI text-embedding-3 models use default settings."""
    # Clear cache
    mongodb._embeddings_cache.clear()
    
    model_name = "text-embedding-3-small"
    mongodb.get_embeddings(model_name)
    
    # Verify OpenAIEmbeddings was called with dimensions parameter
    call_kwargs = mock_openai_embeddings.call_args.kwargs
    assert call_kwargs["model"] == model_name
    assert call_kwargs["dimensions"] == 1536
    assert "check_embedding_ctx_length" not in call_kwargs or call_kwargs["check_embedding_ctx_length"] is True


@patch("app.utils.mongodb.OpenAIEmbeddings")
def test_qwen_embedding_model_disables_tokenization(mock_openai_embeddings):
    """Test that Qwen embedding models disable tokenization for OpenRouter compatibility."""
    # Clear cache
    mongodb._embeddings_cache.clear()
    
    model_name = "qwen/qwen3-embedding-8b"
    mongodb.get_embeddings(model_name)
    
    # Verify OpenAIEmbeddings was called with check_embedding_ctx_length=False
    call_kwargs = mock_openai_embeddings.call_args.kwargs
    assert call_kwargs["model"] == model_name
    assert call_kwargs["check_embedding_ctx_length"] is False
    assert "dimensions" not in call_kwargs


@patch("app.utils.mongodb.OpenAIEmbeddings")
def test_embedding_caching_works(mock_openai_embeddings):
    """Test that embeddings are cached per model."""
    # Clear cache
    mongodb._embeddings_cache.clear()
    
    # Call twice with same model
    model_name = "qwen/qwen3-embedding-8b"
    mongodb.get_embeddings(model_name)
    mongodb.get_embeddings(model_name)
    
    # Should only create once
    assert mock_openai_embeddings.call_count == 1


@patch("app.utils.mongodb.OpenAIEmbeddings")
def test_different_models_create_separate_instances(mock_openai_embeddings):
    """Test that different models create separate embedding instances."""
    # Clear cache
    mongodb._embeddings_cache.clear()
    
    # Call with two different models
    mongodb.get_embeddings("text-embedding-3-small")
    mongodb.get_embeddings("qwen/qwen3-embedding-8b")
    
    # Should create two instances
    assert mock_openai_embeddings.call_count == 2
