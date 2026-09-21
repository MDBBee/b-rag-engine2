import json
import logging
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse

from app.utils.retrieval_pipeline import retrieval_pipeline
from app.typing.schemas import QueryRequest
from app.middleware.auth import get_current_user, UserInfo

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/query/stream")
async def query_stream(request: QueryRequest, user: UserInfo = Depends(get_current_user)):
    async def event_stream():
        try:
            async for event_type, data in retrieval_pipeline(
                query=request.query,
                collection_name=request.collection_name,
                user_id=user.id,
                thread_id=request.thread_id,
                retrieval_settings=request.retrieval_settings,
            ):
                if event_type == "token":
                    yield f"data: {json.dumps({'type': 'token', 'content': data})}\n\n"
                elif event_type == "sources":
                    yield f"data: {json.dumps({'type': 'sources', 'sources': data})}\n\n"
                elif event_type == "done":
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception as e:
            logger.error(f"Query stream failed: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'error': 'Query failed. Please try again.'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
