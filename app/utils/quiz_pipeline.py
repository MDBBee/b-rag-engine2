import logging
from collections.abc import AsyncGenerator

from pydantic import BaseModel, Field

from app.config import settings
from app.typing.schemas import ChatMessageHistory, QuizQuestion
from app.utils import mongodb
from app.utils.assistant_chat_pipeline import assistant_chat_pipeline

logger = logging.getLogger(__name__)

DIFFICULTY_MODIFIERS = {
    'easy': 'Questions should be approachable and focus on foundational concepts.',
    'hard': 'Questions should require careful analysis and the ability to distinguish subtle differences between plausible options.',
}


class QuizQuestions(BaseModel):
    """Wrapper for structured output — list of quiz questions."""

    questions: list[QuizQuestion] = Field(default_factory=list)


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
    project_name: str,
    user_id: str,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    file_scope: list[str] | None = None,
    difficulty: str | None = None,
) -> AsyncGenerator[tuple[str, dict | str | None], None]:
    """Generate quiz questions from document chunks.

    Yields tuples of (event_type, data):
    - ("progress", message) — status updates
    - ("question", question_dict) — one question at a time
    - ("error", message) — fatal error
    - ("done", None) — stream complete
    """
    yield ("progress", "Fetching document chunks...")

    filter_query = {"user_id": user_id, "project_name": project_name}
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

    max_chunks = settings.max_context_chunks
    if len(all_chunks) > max_chunks:
        chunks_to_process = all_chunks[:max_chunks]
        yield ("progress", f"Using first {len(chunks_to_process)} of {len(all_chunks)} chunks...")
    else:
        chunks_to_process = all_chunks
        yield ("progress", f"Processing {len(chunks_to_process)} chunks...")

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

    difficulty_line = ""
    modifier = DIFFICULTY_MODIFIERS.get(difficulty)
    if modifier:
        difficulty_line = f"\nDifficulty adjustment: {modifier}\n"

    prompt = f"""Generate exactly 15 multiple-choice questions from the following document content.

Rules:
- Each question must have exactly 4 options (A, B, C, D)
- Only one option should be correct
- Questions should test understanding, not just recall
- Vary difficulty across questions
- Cover different sections/pages of the document
{difficulty_line}
Rich Content (use the rich_content field for these):
- Include markdown tables when comparing data, presenting structured information, or showing relationships
- Include mermaid diagrams when visualizing processes, flows, hierarchies, or systems (use ```mermaid code blocks)
- Use rich_content to provide context that helps the student reason through the question
- Rich content is optional but strongly encouraged when it adds educational value
- Keep rich_content concise and relevant to the question

Options formatting:
- For lists in options, use: - Item 1\\n- Item 2
- For code in options, use fenced blocks with language tags
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
    project_name: str,
    user_id: str,
    messages: list[ChatMessageHistory] | None = None,
    top_k: int | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    embedding_model: str | None = None,
    skip_context: bool = False,
) -> AsyncGenerator[tuple[str, str | list | dict | None], None]:
    """Explain a quiz question — thin wrapper around assistant_chat_pipeline."""
    context_content = f"""Question: {question}

Options:
A) {option_a}
B) {option_b}
C) {option_c}
D) {option_d}"""

    async for event in assistant_chat_pipeline(
        context_title="Quiz Question",
        context_content=context_content,
        project_name=project_name,
        messages=messages,
        llm_provider=llm_provider,
        llm_model=llm_model,
        skip_context=skip_context,
    ):
        yield event
