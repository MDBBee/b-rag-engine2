from unittest.mock import MagicMock, patch

from app.typing.schemas import ChatMessageHistory
from app.utils.note_chat_pipeline import note_chat_pipeline


class AsyncIterator:
    def __init__(self, items):
        self.items = items
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.items):
            raise StopAsyncIteration
        item = self.items[self.index]
        self.index += 1
        return item


async def test_note_chat_pipeline_yields_model_info():
    with patch("app.utils.assistant_chat_pipeline.mongodb") as mock_mongodb:
        mock_llm = MagicMock()
        mock_chunk = MagicMock()
        mock_chunk.content = "Hello"
        mock_chunk.response_metadata = {"model_name": "openai/gpt-4o-mini"}
        mock_llm.astream.return_value = AsyncIterator([mock_chunk])

        mock_structured_llm = MagicMock()

        async def mock_ainvoke(*args, **kwargs):
            return MagicMock(intent="casual")

        mock_structured_llm.ainvoke = mock_ainvoke
        mock_llm.with_structured_output.return_value = mock_structured_llm
        mock_mongodb.get_openrouter_llm.return_value = mock_llm

        events = []
        async for event_type, data in note_chat_pipeline(
            note_title="Test Note",
            note_markdown="Test content",
            note_query=None,
            project_name="test-project",
            messages=[ChatMessageHistory(role="user", content="Hi")],
            llm_provider="openrouter",
            llm_model="openai/gpt-4o-mini",
        ):
            events.append((event_type, data))

        assert any(
            e[0] == "model_info" and e[1] == "openai/gpt-4o-mini" for e in events
        )


async def test_note_chat_pipeline_no_model_info_if_missing():
    with patch("app.utils.assistant_chat_pipeline.mongodb") as mock_mongodb:
        mock_llm = MagicMock()
        mock_chunk = MagicMock()
        mock_chunk.content = "Hello"
        mock_chunk.response_metadata = {}
        mock_llm.astream.return_value = AsyncIterator([mock_chunk])

        mock_structured_llm = MagicMock()

        async def mock_ainvoke(*args, **kwargs):
            return MagicMock(intent="casual")

        mock_structured_llm.ainvoke = mock_ainvoke
        mock_llm.with_structured_output.return_value = mock_structured_llm
        mock_mongodb.get_openrouter_llm.return_value = mock_llm

        events = []
        async for event_type, data in note_chat_pipeline(
            note_title="Test Note",
            note_markdown="Test content",
            note_query=None,
            project_name="test-project",
            messages=[ChatMessageHistory(role="user", content="Hi")],
            llm_provider="openrouter",
            llm_model="openai/gpt-4o-mini",
        ):
            events.append((event_type, data))

        assert not any(e[0] == "model_info" for e in events)
