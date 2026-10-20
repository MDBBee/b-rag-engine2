import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.config import settings
from app.typing.schemas import ChatMessageHistory, QuizQuestion
from app.utils import mongodb

logger = logging.getLogger(__name__)


class QuizQuestions(BaseModel):
    """Wrapper for structured output — list of quiz questions."""

    questions: list[QuizQuestion] = Field(default_factory=list)


class QuizIntent(BaseModel):
    """Intent classification for quiz chat messages."""

    intent: Literal["casual", "question"] = Field(
        description="casual: greetings, thanks, acknowledgments. question: asking for help, explanation, reasoning, or follow-up about the quiz"
    )


FORMAT_INSTRUCTIONS = """When formatting your response:

Tables - Use proper markdown table syntax:
| Column 1 | Column 2 | Column 3 |
|----------|----------|----------|
| Data     | Data     | Data     |

Lists - Use markdown list syntax:
- Item 1
- Item 2

Code - Use fenced code blocks with language tags:
```python
def example():
    return "code"
```

Never concatenate multiple lines together. Keep cells concise (under 20 words).
"""


async def generate_quiz(
    collection_name: str,
    user_id: str,
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

    total_chars = sum(len(c["text"]) for c in all_chunks)
    estimated_tokens = int(total_chars * 0.75)

    if estimated_tokens > 25000 and len(all_chunks) > 35:
        step = len(all_chunks) // 35
        sampled = [all_chunks[i] for i in range(0, len(all_chunks), step)][:35]
        yield ("progress", f"Sampling {len(sampled)} chunks for quiz generation...")
        chunks_to_process = sampled
    else:
        yield ("progress", f"Processing {len(all_chunks)} chunks...")
        chunks_to_process = all_chunks

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
        try:
            llm = mongodb.get_openrouter_llm(llm_model or settings.llm_model)
        except ValueError as e:
            yield ("error", str(e))
            yield ("done", None)
            return

    yield ("progress", "Generating quiz questions...")

    context_parts = []
    for i, chunk in enumerate(chunks_to_process, 1):
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
- When using tables in questions/options, use proper markdown:
| Column 1 | Column 2 |
|----------|----------|
| Data     | Data     |
- For lists, use: - Item 1\n- Item 2
- For code, use fenced blocks with language tags
- Never concatenate multiple lines together

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


async def reword_quiz(
    questions: list[QuizQuestion],
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> AsyncGenerator[tuple[str, dict | str | None], None]:
    """Rephrase existing quiz questions with different wording.
    
    Yields tuples of (event_type, data):
    - ("progress", message) — status updates
    - ("question", question_dict) — one reworded question at a time
    - ("error", message) — fatal error
    - ("done", None) — stream complete
    """
    if not questions:
        yield ("error", "No questions provided for rewording.")
        yield ("done", None)
        return

    yield ("progress", f"Rewording {len(questions)} questions...")

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
        try:
            llm = mongodb.get_openrouter_llm(llm_model or settings.llm_model)
        except ValueError as e:
            yield ("error", str(e))
            yield ("done", None)
            return

    # Build the original questions text for the prompt
    questions_text = []
    for i, q in enumerate(questions, 1):
        questions_text.append(
            f"Question {i}:\n"
            f"{q.question}\n"
            f"A) {q.option_a}\n"
            f"B) {q.option_b}\n"
            f"C) {q.option_c}\n"
            f"D) {q.option_d}\n"
            f"Correct: {q.correct_answer}"
        )

    questions_str = "\n\n".join(questions_text)

    prompt = f"""Rephrase the following quiz questions while maintaining their meaning and difficulty level.

Rules:
- Rewrite each question with different wording but keep the same meaning and difficulty
- Rewrite all four options (A, B, C, D) with different wording but maintain their meaning
- IMPORTANT: Change which option letter contains the correct answer
  * If the original correct answer was A, move it to B, C, or D
  * If the original correct answer was B, move it to A, C, or D
  * If the original correct answer was C, move it to A, B, or D
  * If the original correct answer was D, move it to A, B, or C
- Ensure exactly one option is correct in each reworded question
- Maintain the same format: question text, four options, and indicate the new correct answer letter

Original questions:
{questions_str}"""

    try:
        structured_llm = llm.with_structured_output(QuizQuestions, method="json_schema")
        result = await structured_llm.ainvoke([prompt])

        if not result or not result.questions or len(result.questions) != len(questions):
            yield ("error", "Failed to reword questions. Please try again.")
            yield ("done", None)
            return

        for q in result.questions:
            yield ("question", q.model_dump())

        yield ("progress", f"Reworded {len(result.questions)} questions.")

    except Exception as e:
        logger.exception("Quiz rewording failed")
        yield ("error", f"Failed to reword questions: {e}")

    yield ("done", None)


async def quiz_explain_pipeline(
    question: str,
    option_a: str,
    option_b: str,
    option_c: str,
    option_d: str,
    collection_name: str,
    user_id: str,
    messages: list[ChatMessageHistory] | None = None,
    top_k: int | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    embedding_model: str | None = None,
) -> AsyncGenerator[tuple[str, str | list | None], None]:
    """Explain a quiz question using document context (no intent/rephrase overhead).

    Yields tuples of (event_type, data):
    - ("token", token_string) — streamed response tokens
    - ("sources", source_list) — retrieved document chunks
    - ("error", message) — fatal error
    - ("done", None) — stream complete
    """
    resolved_provider = llm_provider or "openrouter"
    resolved_model = llm_model or settings.llm_model

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
        try:
            llm = mongodb.get_openrouter_llm(resolved_model)
        except ValueError as e:
            yield ("error", str(e))
            yield ("done", None)
            return

    # Extract latest user message from history
    latest_user_msg = None
    if messages:
        for m in reversed(messages):
            if m.role == "user":
                latest_user_msg = m.content
                break

    if not latest_user_msg:
        yield ("error", "No user message found")
        yield ("done", None)
        return

    # Classify intent
    try:
        structured_llm = llm.with_structured_output(QuizIntent, method="json_schema")
        intent_result = await structured_llm.ainvoke([
            SystemMessage(content="Classify the user's message as 'casual' (greetings, thanks, short acknowledgments) or 'question' (asking for help, explanation, reasoning, or follow-up about the quiz question)."),
            HumanMessage(content=latest_user_msg),
        ])
        is_casual = intent_result.intent == "casual"
    except Exception:
        logger.warning("Intent classification failed, treating as question", exc_info=True)
        is_casual = False

    # Build message history for LLM
    all_messages = []
    if messages:
        for m in messages:
            if m.role == "user":
                all_messages.append(HumanMessage(content=m.content))
            else:
                all_messages.append(AIMessage(content=m.content))

    today = datetime.now(tz=UTC).strftime("%B %d, %Y")
    quiz_context = f"""Question: {question}

Options:
A) {option_a}
B) {option_b}
C) {option_c}
D) {option_d}"""

    if is_casual:
        system_prompt = f"""You are a friendly quiz tutor. Today's date is {today}.

The user is having a conversation about this quiz question:

{quiz_context}

{FORMAT_INSTRUCTIONS}
Respond naturally and conversationally. Keep it brief."""

        try:
            async for chunk in llm.astream([SystemMessage(content=system_prompt)] + all_messages):
                if chunk.content:
                    yield ("token", chunk.content)
            yield ("sources", [])
            yield ("done", None)
        except Exception as e:
            logger.exception("Quiz explain failed")
            yield ("error", f"Failed to explain: {e}")
            yield ("done", None)
        return

    # Vector search for real questions
    top_k = top_k or settings.top_k
    pre_filter = {"user_id": user_id, "collection_name": collection_name}

    vectorstore = mongodb.get_vectorstore(embedding_model)
    docs = await vectorstore.asimilarity_search(question, k=top_k, pre_filter=pre_filter)

    # Build context
    context = ""
    if docs:
        context_parts = []
        for i, doc in enumerate(docs, 1):
            source = doc.metadata.get("source", "Unknown")
            chunk_idx = doc.metadata.get("chunk_index", "N/A")
            context_parts.append(f"[Source: {source}, chunk {chunk_idx}]\n{doc.page_content}")
        context = "\n\n".join(context_parts)

    # Build sources
    sources = []
    for i, doc in enumerate(docs, 1):
        sources.append({
            "chunk_id": str(doc.metadata.get("chunk_index", i)),
            "content_preview": doc.page_content[:300],
            "source": doc.metadata.get("source"),
        })

    system_prompt = f"""You are a helpful quiz tutor. Today's date is {today}.

The user is asking about this quiz question:

{quiz_context}

{FORMAT_INSTRUCTIONS}
Explain what the question is asking, reason through each option using the document context below, and help the user understand which answer is correct and why.

IMPORTANT: Always base your answer on the document context below. If the context doesn't contain relevant information, say so explicitly — do not fall back to general knowledge. Reference specific passages when explaining.

Document context:
{context}"""

    try:
        async for chunk in llm.astream([SystemMessage(content=system_prompt)] + all_messages):
            if chunk.content:
                yield ("token", chunk.content)
        yield ("sources", sources)
        yield ("done", None)
    except Exception as e:
        logger.exception("Quiz explain failed")
        yield ("error", f"Failed to explain: {e}")
        yield ("done", None)
