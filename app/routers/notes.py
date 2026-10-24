import json
import logging
from collections.abc import AsyncIterable

from fastapi import APIRouter, Depends, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.limiter import limiter
from app.middleware.auth import UserInfo, get_current_user
from app.typing.schemas import NoteChatRequest
from app.utils.note_chat_pipeline import note_chat_pipeline

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/notes",
    tags=["notes"],
)


@router.post("/chat", response_class=EventSourceResponse)
@limiter.limit("10/minute")
async def note_chat(
    request: Request,
    chat_request: NoteChatRequest,
    user: UserInfo = Depends(get_current_user),
) -> AsyncIterable[ServerSentEvent]:
    """SSE streaming chat about a note with document context."""
    logger.info(
        "Note chat: title=%s, project=%s, model=%s, messages=%d",
        chat_request.note_title[:50],
        chat_request.project_name,
        chat_request.llm_model,
        len(chat_request.messages),
    )

    try:
        async for event_type, data in note_chat_pipeline(
            note_title=chat_request.note_title,
            note_markdown=chat_request.note_markdown,
            note_query=chat_request.note_query,
            project_name=chat_request.project_name,
            messages=chat_request.messages,
            llm_provider=chat_request.llm_provider,
            llm_model=chat_request.llm_model,
        ):
            if event_type == "token":
                yield ServerSentEvent(raw_data=json.dumps({"type": "token", "content": data}))
            elif event_type == "sources":
                yield ServerSentEvent(raw_data=json.dumps({"type": "sources", "sources": data}))
            elif event_type == "web_sources":
                yield ServerSentEvent(raw_data=json.dumps({"type": "web_sources", "sources": data}))
            elif event_type == "model_info":
                yield ServerSentEvent(raw_data=json.dumps({"type": "model_info", "model": data}))
            elif event_type == "done":
                yield ServerSentEvent(raw_data=json.dumps({"type": "done"}))
            elif event_type == "error":
                yield ServerSentEvent(raw_data=json.dumps({"type": "error", "content": data}))
    except Exception:
        logger.exception("Note chat stream failed")
        yield ServerSentEvent(raw_data=json.dumps({"type": "error", "content": "Chat failed. Please try again."}))
