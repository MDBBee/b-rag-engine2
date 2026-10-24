import json
import logging
import re
from collections.abc import AsyncIterable

from fastapi import APIRouter, Depends, Request, Response
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.limiter import limiter
from app.middleware.auth import UserInfo, get_current_user
from app.typing.schemas import QueryRequest, SummaryExportRequest
from app.utils.pdf_generator import markdown_to_pdf
from app.utils.retrieval_pipeline import retrieval_pipeline

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/query",
    tags=["retrieval"],
)

NODE_EVENT_MAP = {
    "classify_intent": ("searching", "Analyzing query..."),
    "retrieve_all": ("searching", "Loading document..."),
    "retrieve_top_k": ("searching", "Searching documents..."),
    "rephrase_query": ("rephrasing", "Rephrasing query..."),
    "generate": ("generating", "Generating answer..."),
    "generate_direct": ("generating", "Generating answer..."),
    "web_research": ("searching", "Searching the web..."),
    "generate_with_web_context": ("generating", "Generating answer..."),
}


@router.post("/stream", response_class=EventSourceResponse)
@limiter.limit("20/minute")
async def query_stream(
    request: Request,
    query_request: QueryRequest, user: UserInfo = Depends(get_current_user)
) -> AsyncIterable[ServerSentEvent]:
    logger.info(
        "Query request: project=%s, model=%s, provider=%s, messages=%d",
        query_request.project_name,
        query_request.llm_model,
        query_request.llm_provider,
        len(query_request.messages),
    )

    try:
        async for event_type, data in retrieval_pipeline(
            query=query_request.query,
            project_name=query_request.project_name,
            user_id=user.id,
            messages=query_request.messages,
            file_name=query_request.file_name,
            top_k=query_request.top_k,
            summary_chunks=query_request.summary_chunks,
            max_retries=query_request.max_retries,
            llm_provider=query_request.llm_provider,
            llm_model=query_request.llm_model,
            file_scope=query_request.file_scope,
            embedding_model=query_request.embedding_model,
        ):
            if event_type == "node_start":
                fe_type, message = NODE_EVENT_MAP.get(data, (None, None))
                if fe_type:
                    yield ServerSentEvent(raw_data=json.dumps({"type": fe_type, "message": message}))
            elif event_type == "token":
                yield ServerSentEvent(raw_data=json.dumps({"type": "token", "content": data}))
            elif event_type == "sources":
                yield ServerSentEvent(raw_data=json.dumps({"type": "sources", "sources": data}))
            elif event_type == "web_sources":
                yield ServerSentEvent(raw_data=json.dumps({"type": "web_sources", "sources": data}))
            elif event_type == "usage":
                yield ServerSentEvent(raw_data=json.dumps({"type": "usage", "usage": data}))
            elif event_type == "model_info":
                yield ServerSentEvent(raw_data=json.dumps({"type": "model_info", "model": data}))
            elif event_type == "done":
                yield ServerSentEvent(raw_data=json.dumps({"type": "done"}))
    except Exception:
        logger.exception("Query stream failed")
        yield ServerSentEvent(raw_data=json.dumps({"type": "error", "message": "Query failed. Please try again."}))


@router.post("/export/pdf")
async def export_summary_pdf(
    request: SummaryExportRequest,
    user: UserInfo = Depends(get_current_user),
):
    """Export summary as PDF file."""
    pdf_bytes = markdown_to_pdf(request.markdown_text, request.title)

    safe_title = re.sub(r"[^\w\s-]", "", request.title).strip()[:50]
    filename = f"{safe_title}.pdf" if safe_title else "summary.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/export/markdown")
async def export_summary_markdown(
    request: SummaryExportRequest,
    user: UserInfo = Depends(get_current_user),
):
    """Export summary as Markdown file."""
    safe_title = re.sub(r"[^\w\s-]", "", request.title).strip()[:50]
    filename = f"{safe_title}.md" if safe_title else "summary.md"

    return Response(
        content=request.markdown_text,
        media_type="text/markdown",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
