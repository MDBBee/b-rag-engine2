from collections.abc import AsyncGenerator

from app.typing.schemas import ChatMessageHistory
from app.utils.assistant_chat_pipeline import assistant_chat_pipeline


async def note_chat_pipeline(
    note_title: str,
    note_markdown: str,
    note_query: str | None,
    project_name: str,
    messages: list[ChatMessageHistory] | None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> AsyncGenerator[tuple[str, str | list | None], None]:
    """AI assistant chat about a note — thin wrapper around assistant_chat_pipeline."""
    context_content = note_markdown

    async for event in assistant_chat_pipeline(
        context_title=note_title,
        context_content=context_content,
        context_query=note_query,
        project_name=project_name,
        messages=messages,
        llm_provider=llm_provider,
        llm_model=llm_model,
    ):
        yield event
