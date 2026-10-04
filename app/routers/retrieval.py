import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.middleware.auth import UserInfo, get_current_user
from app.typing.schemas import QueryRequest
from app.utils.retrieval_pipeline import retrieval_pipeline

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/query",
    tags=["retrieval"],
)

NODE_EVENT_MAP = {
    "router": ("searching", "Analyzing query..."),
    "retrieve": ("searching", "Searching documents..."),
    "rephrase_query": ("rephrasing", "Rephrasing query..."),
    "generate": ("generating", "Generating answer..."),
}


@router.post("/stream")
async def query_stream(request: QueryRequest, user: UserInfo = Depends(get_current_user)):
    print(f"REQUEST:::===::: {request}")
    async def event_stream():
        try:
            async for event_type, data in retrieval_pipeline(
                query=request.query,
                collection_name=request.collection_name,
                user_id=user.id,
                messages=request.messages,
                project_name=request.project_name,
                file_name=request.file_name,
                top_k=request.top_k,
                max_retries=request.max_retries,
                llm_provider=request.llm_provider,
                llm_model=request.llm_model,
            ):
                if event_type == "node_start":
                    fe_type, message = NODE_EVENT_MAP.get(data, (None, None))
                    if fe_type:
                        yield f"data: {json.dumps({'type': fe_type, 'message': message})}\n\n"
                elif event_type == "token":
                    yield f"data: {json.dumps({'type': 'token', 'content': data})}\n\n"
                elif event_type == "sources":
                    yield f"data: {json.dumps({'type': 'sources', 'sources': data})}\n\n"
                elif event_type == "done":
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
        except Exception:
            logger.exception("Query stream failed")
            yield f"data: {json.dumps({'type': 'error', 'content': 'Query failed. Please try again.'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
