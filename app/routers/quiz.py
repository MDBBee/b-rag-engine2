import json
import logging
from collections.abc import AsyncIterable

from fastapi import APIRouter, Depends
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.middleware.auth import UserInfo, get_current_user
from app.typing.schemas import QuizExplainRequest, QuizRequest, RewordRequest
from app.utils.quiz_pipeline import generate_quiz, quiz_explain_pipeline, reword_quiz

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/quiz",
    tags=["quiz"],
)


@router.post("/generate", response_class=EventSourceResponse)
async def generate(
    request: QuizRequest, user: UserInfo = Depends(get_current_user)
) -> AsyncIterable[ServerSentEvent]:
    try:
        async for event_type, data in generate_quiz(
            collection_name=request.collection_name,
            user_id=user.id,
            llm_provider=request.llm_provider,
            llm_model=request.llm_model,
            file_scope=request.file_scope,
        ):
            if event_type == "progress":
                yield ServerSentEvent(raw_data=json.dumps({"type": "progress", "message": data}))
            elif event_type == "question":
                yield ServerSentEvent(raw_data=json.dumps({"type": "question", "question": data}))
            elif event_type == "error":
                yield ServerSentEvent(raw_data=json.dumps({"type": "error", "message": data}))
            elif event_type == "done":
                yield ServerSentEvent(raw_data=json.dumps({"type": "done"}))
    except Exception:
        logger.exception("Quiz generation stream failed")
        yield ServerSentEvent(raw_data=json.dumps({"type": "error", "message": "Quiz generation failed. Please try again."}))
        yield ServerSentEvent(raw_data=json.dumps({"type": "done"}))


@router.post("/reword", response_class=EventSourceResponse)
async def reword(
    request: RewordRequest, user: UserInfo = Depends(get_current_user)
) -> AsyncIterable[ServerSentEvent]:
    try:
        async for event_type, data in reword_quiz(
            questions=request.questions,
        ):
            if event_type == "progress":
                yield ServerSentEvent(raw_data=json.dumps({"type": "progress", "message": data}))
            elif event_type == "question":
                yield ServerSentEvent(raw_data=json.dumps({"type": "question", "question": data}))
            elif event_type == "error":
                yield ServerSentEvent(raw_data=json.dumps({"type": "error", "message": data}))
            elif event_type == "done":
                yield ServerSentEvent(raw_data=json.dumps({"type": "done"}))
    except Exception:
        logger.exception("Quiz reword stream failed")
        yield ServerSentEvent(raw_data=json.dumps({"type": "error", "message": "Quiz reword failed. Please try again."}))
        yield ServerSentEvent(raw_data=json.dumps({"type": "done"}))


@router.post("/explain", response_class=EventSourceResponse)
async def explain(
    request: QuizExplainRequest, user: UserInfo = Depends(get_current_user)
) -> AsyncIterable[ServerSentEvent]:
    try:
        async for event_type, data in quiz_explain_pipeline(
            question=request.question,
            option_a=request.option_a,
            option_b=request.option_b,
            option_c=request.option_c,
            option_d=request.option_d,
            collection_name=request.collection_name,
            user_id=user.id,
            messages=request.messages,
            top_k=request.top_k,
            llm_provider=request.llm_provider,
            llm_model=request.llm_model,
        ):
            if event_type == "token":
                yield ServerSentEvent(raw_data=json.dumps({"type": "token", "content": data}))
            elif event_type == "sources":
                yield ServerSentEvent(raw_data=json.dumps({"type": "sources", "sources": data}))
            elif event_type == "error":
                yield ServerSentEvent(raw_data=json.dumps({"type": "error", "content": data}))
            elif event_type == "done":
                yield ServerSentEvent(raw_data=json.dumps({"type": "done"}))
    except Exception:
        logger.exception("Quiz explain stream failed")
        yield ServerSentEvent(raw_data=json.dumps({"type": "error", "content": "Quiz explain failed. Please try again."}))
        yield ServerSentEvent(raw_data=json.dumps({"type": "done"}))
