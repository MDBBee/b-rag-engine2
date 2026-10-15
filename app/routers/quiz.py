import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.middleware.auth import UserInfo, get_current_user
from app.typing.schemas import QuizRequest, RewordRequest
from app.utils.quiz_pipeline import generate_quiz, reword_quiz_questions

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/quiz",
    tags=["quiz"],
)


@router.post("/generate")
async def generate(request: QuizRequest, user: UserInfo = Depends(get_current_user)):
    async def event_stream():
        try:
            async for event_type, data in generate_quiz(
                collection_name=request.collection_name,
                user_id=user.id,
                page_start=request.page_start,
                page_end=request.page_end,
                llm_provider=request.llm_provider,
                llm_model=request.llm_model,
            ):
                if event_type == "progress":
                    yield f"data: {json.dumps({'type': 'progress', 'message': data})}\n\n"
                elif event_type == "question":
                    yield f"data: {json.dumps({'type': 'question', 'question': data})}\n\n"
                elif event_type == "error":
                    yield f"data: {json.dumps({'type': 'error', 'message': data})}\n\n"
                elif event_type == "done":
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception:
            logger.exception("Quiz generation stream failed")
            yield f"data: {json.dumps({'type': 'error', 'message': 'Quiz generation failed. Please try again.'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/reword")
async def reword(request: RewordRequest, user: UserInfo = Depends(get_current_user)):
    async def event_stream():
        try:
            async for event_type, data in reword_quiz_questions(
                questions=request.questions,
            ):
                if event_type == "progress":
                    yield f"data: {json.dumps({'type': 'progress', 'message': data})}\n\n"
                elif event_type == "question":
                    yield f"data: {json.dumps({'type': 'question', 'question': data})}\n\n"
                elif event_type == "error":
                    yield f"data: {json.dumps({'type': 'error', 'message': data})}\n\n"
                elif event_type == "done":
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception:
            logger.exception("Quiz reword stream failed")
            yield f"data: {json.dumps({'type': 'error', 'message': 'Quiz reword failed. Please try again.'})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
