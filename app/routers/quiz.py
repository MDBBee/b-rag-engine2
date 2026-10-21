import json
import logging
from collections.abc import AsyncIterable

from fastapi import APIRouter, Depends, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.limiter import limiter
from app.middleware.auth import UserInfo, get_current_user
from app.typing.schemas import QuizExplainRequest, QuizRequest, RewordRequest
from app.utils.quiz_pipeline import generate_quiz, quiz_explain_pipeline, reword_quiz

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/quiz",
    tags=["quiz"],
)


@router.post("/generate", response_class=EventSourceResponse)
@limiter.limit("10/minute")
async def generate(
    request: Request,
    query: QuizRequest, user: UserInfo = Depends(get_current_user)
) -> AsyncIterable[ServerSentEvent]:
    try:
        async for event_type, data in generate_quiz(
            project_name=query.project_name,
            user_id=user.id,
            llm_provider=query.llm_provider,
            llm_model=query.llm_model,
            file_scope=query.file_scope,
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
@limiter.limit("10/minute")
async def reword(
    request: Request,
    query: RewordRequest, user: UserInfo = Depends(get_current_user)
) -> AsyncIterable[ServerSentEvent]:
    try:
        async for event_type, data in reword_quiz(
            questions=query.questions,
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
@limiter.limit("10/minute")
async def explain(
    request: Request,
    query: QuizExplainRequest, user: UserInfo = Depends(get_current_user)
) -> AsyncIterable[ServerSentEvent]:
    try:
        async for event_type, data in quiz_explain_pipeline(
            question=query.question,
            option_a=query.option_a,
            option_b=query.option_b,
            option_c=query.option_c,
            option_d=query.option_d,
            project_name=query.project_name,
            user_id=user.id,
            messages=query.messages,
            top_k=query.top_k,
            llm_provider=query.llm_provider,
            llm_model=query.llm_model,
        ):
            if event_type == "token":
                yield ServerSentEvent(raw_data=json.dumps({"type": "token", "content": data}))
            elif event_type == "sources":
                yield ServerSentEvent(raw_data=json.dumps({"type": "sources", "sources": data}))
            elif event_type == "error":
                yield ServerSentEvent(raw_data=json.dumps({"type": "error", "message": data}))
            elif event_type == "done":
                yield ServerSentEvent(raw_data=json.dumps({"type": "done"}))
    except Exception:
        logger.exception("Quiz explain stream failed")
        yield ServerSentEvent(raw_data=json.dumps({"type": "error", "message": "Quiz explain failed. Please try again."}))
        yield ServerSentEvent(raw_data=json.dumps({"type": "done"}))
