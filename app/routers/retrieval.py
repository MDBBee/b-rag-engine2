import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.middleware.auth import UserInfo, get_current_user
from app.typing.schemas import QueryRequest
from app.utils.retrieval_pipeline import retrieval_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/query/stream")
async def query_stream(request: QueryRequest, user: UserInfo = Depends(get_current_user)):
    print("QUERY:", request)

    async def event_stream():
        try:
            async for event_type, data in retrieval_pipeline(
                query=request.query,
                collection_name=request.collection_name,
                user_id=user.id,
                messages=request.messages,
                llm_model=request.llm_model,
                project_name=request.project_name,
                file_name=request.file_name,
            ):
                if event_type == "token":
                    yield f"data: {json.dumps({'type': 'token', 'content': data})}\n\n"
                elif event_type == "sources":
                    yield f"data: {json.dumps({'type': 'sources', 'sources': data})}\n\n"
                elif event_type == "done":
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception:
            logger.exception("Query stream failed")
            yield f"data: {json.dumps({'type': 'error', 'error': 'Query failed. Please try again.'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
