from unittest.mock import AsyncMock, MagicMock, patch

from app.typing.schemas import ChatMessageHistory
from app.utils.retrieval_pipeline import retrieval_pipeline


async def test_retrieval_pipeline_yields_model_info_from_chat_model_end():
    with patch("app.utils.retrieval_pipeline.mongodb") as mock_mongodb, \
         patch("app.utils.retrieval_pipeline.get_compiled_graph") as mock_get_graph:

        mock_llm = MagicMock()
        mock_llm.model = "openai/gpt-4o-mini"
        mock_mongodb.get_openrouter_llm.return_value = mock_llm

        mock_ai_message = MagicMock()
        mock_ai_message.response_metadata = {"model_name": "openai/gpt-4o-mini"}

        mock_graph = MagicMock()

        async def mock_stream(*args, **kwargs):
            yield {
                "event": "on_chat_model_end",
                "metadata": {"langgraph_node": "generate"},
                "data": {"output": mock_ai_message}
            }
            yield {
                "event": "done",
                "metadata": {},
                "data": {}
            }

        mock_graph.astream_events = mock_stream
        mock_get_graph.return_value = mock_graph

        events = []
        async for event_type, data in retrieval_pipeline(
            query="What is this about?",
            project_name="test-collection",
            user_id="user-123",
            messages=[]
        ):
            events.append((event_type, data))

        assert any(
            e[0] == "model_info" and e[1] == "openai/gpt-4o-mini" for e in events
        )


async def test_retrieval_pipeline_no_model_info_if_missing():
    with patch("app.utils.retrieval_pipeline.mongodb") as mock_mongodb, \
         patch("app.utils.retrieval_pipeline.get_compiled_graph") as mock_get_graph:

        mock_llm = MagicMock()
        mock_llm.model = "openai/gpt-4o-mini"
        mock_mongodb.get_openrouter_llm.return_value = mock_llm

        mock_ai_message = MagicMock()
        mock_ai_message.response_metadata = {}

        mock_graph = MagicMock()

        async def mock_stream(*args, **kwargs):
            yield {
                "event": "on_chat_model_end",
                "metadata": {"langgraph_node": "generate"},
                "data": {"output": mock_ai_message}
            }
            yield {
                "event": "done",
                "metadata": {},
                "data": {}
            }

        mock_graph.astream_events = mock_stream
        mock_get_graph.return_value = mock_graph

        events = []
        async for event_type, data in retrieval_pipeline(
            query="What is this about?",
            project_name="test-collection",
            user_id="user-123",
            messages=[]
        ):
            events.append((event_type, data))

        assert not any(e[0] == "model_info" for e in events)


async def test_retrieval_pipeline_yields_model_info_only_once():
    with patch("app.utils.retrieval_pipeline.mongodb") as mock_mongodb, \
         patch("app.utils.retrieval_pipeline.get_compiled_graph") as mock_get_graph:

        mock_llm = MagicMock()
        mock_llm.model = "openai/gpt-4o-mini"
        mock_mongodb.get_openrouter_llm.return_value = mock_llm

        mock_ai_message = MagicMock()
        mock_ai_message.response_metadata = {"model_name": "openai/gpt-4o-mini"}

        mock_graph = MagicMock()

        async def mock_stream(*args, **kwargs):
            yield {
                "event": "on_chat_model_end",
                "metadata": {"langgraph_node": "generate"},
                "data": {"output": mock_ai_message}
            }
            yield {
                "event": "on_chat_model_end",
                "metadata": {"langgraph_node": "generate_direct"},
                "data": {"output": mock_ai_message}
            }
            yield {
                "event": "done",
                "metadata": {},
                "data": {}
            }

        mock_graph.astream_events = mock_stream
        mock_get_graph.return_value = mock_graph

        events = []
        async for event_type, data in retrieval_pipeline(
            query="What is this about?",
            project_name="test-collection",
            user_id="user-123",
            messages=[]
        ):
            events.append((event_type, data))

        model_info_events = [e for e in events if e[0] == "model_info"]
        assert len(model_info_events) == 1
