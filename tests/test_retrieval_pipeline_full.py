from unittest.mock import MagicMock, patch

import pytest

from app.typing.schemas import ChatMessageHistory
from app.utils.retrieval_pipeline import (
    build_graph,
    init_graph,
    retrieval_pipeline,
)


@pytest.mark.asyncio
async def test_retrieval_pipeline_metadata_fast_path():
    events = []
    async for event_type, data in retrieval_pipeline(
        query="what is the file name",
        collection_name="test-collection",
        user_id="user-123",
        file_name="document.pdf"
    ):
        events.append((event_type, data))
    
    assert any(e[0] == "sources" for e in events)
    assert any(e[0] == "token" for e in events)
    assert any(e[0] == "done" for e in events)


@pytest.mark.asyncio
async def test_retrieval_pipeline_with_graph():
    with patch("app.utils.retrieval_pipeline.mongodb") as mock_mongodb, \
         patch("app.utils.retrieval_pipeline.get_compiled_graph") as mock_get_graph:
        
        mock_llm = MagicMock()
        mock_mongodb.llm = mock_llm
        
        mock_graph = MagicMock()
        async def mock_stream(*args, **kwargs):
            yield {
                "event": "on_chain_start",
                "metadata": {"langgraph_node": "router"}
            }
            yield {
                "event": "on_chat_model_stream",
                "metadata": {"langgraph_node": "generate"},
                "data": {"chunk": MagicMock(content="Answer")}
            }
        mock_graph.astream_events = mock_stream
        mock_get_graph.return_value = mock_graph
        
        events = []
        async for event_type, data in retrieval_pipeline(
            query="What is this about?",
            collection_name="test-collection",
            user_id="user-123",
            messages=[]
        ):
            events.append((event_type, data))
        
        assert len(events) > 0


@pytest.mark.asyncio
async def test_retrieval_pipeline_with_messages():
    with patch("app.utils.retrieval_pipeline.mongodb") as mock_mongodb, \
         patch("app.utils.retrieval_pipeline.get_compiled_graph") as mock_get_graph:
        
        mock_llm = MagicMock()
        mock_mongodb.llm = mock_llm
        
        mock_graph = MagicMock()
        async def mock_stream(*args, **kwargs):
            yield {
                "event": "on_chain_end",
                "metadata": {"langgraph_node": "generate"}
            }
        mock_graph.astream_events = mock_stream
        mock_get_graph.return_value = mock_graph
        
        messages = [
            ChatMessageHistory(role="user", content="Previous question"),
            ChatMessageHistory(role="assistant", content="Previous answer")
        ]
        
        events = []
        async for event_type, data in retrieval_pipeline(
            query="Follow up",
            collection_name="test-collection",
            user_id="user-123",
            messages=messages
        ):
            events.append((event_type, data))
        
        assert any(e[0] == "done" for e in events)


def test_build_graph_structure():
    with patch("app.utils.retrieval_pipeline.settings") as mock_settings:
        mock_settings.rephrase_enabled = True
        graph = build_graph()
        assert graph is not None


def test_init_graph():
    with patch("app.utils.retrieval_pipeline.settings") as mock_settings:
        mock_settings.rephrase_enabled = False
        init_graph()
        from app.utils.retrieval_pipeline import compiled_graph
        assert compiled_graph is not None


@pytest.mark.asyncio
async def test_retrieval_pipeline_ollama_provider():
    with patch("app.utils.retrieval_pipeline.mongodb") as mock_mongodb, \
         patch("app.utils.retrieval_pipeline.get_compiled_graph") as mock_get_graph:
        
        mock_get_llm = MagicMock()
        mock_mongodb.get_llm.return_value = mock_get_llm
        
        mock_graph = MagicMock()
        async def mock_stream(*args, **kwargs):
            yield {"event": "on_chain_end", "metadata": {"langgraph_node": "generate"}}
        mock_graph.astream_events = mock_stream
        mock_get_graph.return_value = mock_graph
        
        events = []
        async for event_type, data in retrieval_pipeline(
            query="Test query",
            collection_name="test-collection",
            user_id="user-123",
            llm_provider="ollama",
            llm_model="llama2",
            messages=[]
        ):
            events.append((event_type, data))
        
        mock_mongodb.get_llm.assert_called_once_with("llama2")


@pytest.mark.asyncio
async def test_retrieval_pipeline_ollama_no_model():
    events = []
    async for event_type, data in retrieval_pipeline(
        query="Test query",
        collection_name="test-collection",
        user_id="user-123",
        llm_provider="ollama",
        llm_model=None,
        messages=[]
    ):
        events.append((event_type, data))
    
    assert any(e[0] == "error" for e in events)
    assert any("model" in str(e[1]).lower() for e in events if e[0] == "error")
