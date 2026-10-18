import logging
from collections.abc import AsyncGenerator

from pydantic import BaseModel, Field

from app.typing.schemas import QuizQuestion
from app.utils import mongodb

logger = logging.getLogger(__name__)


class QuizQuestions(BaseModel):
    """Wrapper for structured output — list of quiz questions."""

    questions: list[QuizQuestion] = Field(default_factory=list)


async def generate_quiz(
    collection_name: str,
    user_id: str,
    page_start: int | None = None,
    page_end: int | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    file_scope: list[str] | None = None,
) -> AsyncGenerator[tuple[str, dict | str | None], None]:
    """Generate quiz questions from document chunks.

    Yields tuples of (event_type, data):
    - ("progress", message) — status updates
    - ("question", question_dict) — one question at a time
    - ("error", message) — fatal error
    - ("done", None) — stream complete
    """
    yield ("progress", "Fetching document chunks...")

    filter_query = {"user_id": user_id, "collection_name": collection_name}
    if file_scope:
        filter_query["metadata.source"] = {"$in": file_scope}

    cursor = mongodb.vectors.find(filter_query).sort("chunk_index", 1)

    all_chunks = []
    async for doc in cursor:
        all_chunks.append({
            "text": doc.get("content", ""),
            "metadata": doc.get("metadata", {}),
        })

    if not all_chunks:
        yield ("error", "No chunks found for this collection.")
        yield ("done", None)
        return

    filtered_chunks = all_chunks

    if page_start is not None and page_end is not None:
        page_filtered = [
            c for c in all_chunks
            if c["metadata"].get("page_number") is not None
            and page_start <= c["metadata"]["page_number"] <= page_end
        ]
        if page_filtered:
            filtered_chunks = page_filtered
        else:
            yield ("progress", "Page range not available, using full document.")

    total_chars = sum(len(c["text"]) for c in filtered_chunks)
    estimated_tokens = int(total_chars * 0.75)

    if estimated_tokens > 25000 and len(filtered_chunks) > 35:
        step = len(filtered_chunks) // 35
        sampled = [filtered_chunks[i] for i in range(0, len(filtered_chunks), step)][:35]
        filtered_chunks = sampled
        yield ("progress", f"Sampling {len(filtered_chunks)} chunks for quiz generation...")
    else:
        yield ("progress", f"Processing {len(filtered_chunks)} chunks...")

    resolved_provider = llm_provider or "openrouter"

    if resolved_provider == "ollama":
        if not llm_model:
            yield ("error", "Ollama provider selected but no model specified.")
            yield ("done", None)
            return
        try:
            llm = mongodb.get_llm(llm_model)
        except ValueError as e:
            yield ("error", str(e))
            yield ("done", None)
            return
    else:
        llm = mongodb.llm

    yield ("progress", "Generating quiz questions...")

    context_parts = []
    for i, chunk in enumerate(filtered_chunks, 1):
        page = chunk["metadata"].get("page_number", "?")
        context_parts.append(f"[Page {page}, Chunk {i}]\n{chunk['text']}")

    context = "\n\n".join(context_parts)

    prompt = f"""Generate exactly 15 multiple-choice questions from the following document content.

Rules:
- Each question must have exactly 4 options (A, B, C, D)
- Only one option should be correct
- Questions should test understanding, not just recall
- Vary difficulty across questions
- Cover different sections/pages of the document
- When using structured content in questions or options (tables, lists, diagrams, code blocks), ensure every element is on its own line with proper spacing

Document content:
{context}"""

    try:
        structured_llm = llm.with_structured_output(QuizQuestions, method="json_schema")
        result = await structured_llm.ainvoke([prompt])

        if not result or not result.questions:
            yield ("error", "Failed to generate questions. Please try again.")
            yield ("done", None)
            return

        for q in result.questions:
            yield ("question", q.model_dump())

        yield ("progress", f"Generated {len(result.questions)} questions.")

    except Exception as e:
        logger.exception("Quiz generation failed")
        yield ("error", f"Failed to generate questions: {e}")

    yield ("done", None)
