import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.config import settings
from app.typing.schemas import ChatMessageHistory
from app.utils import mongodb
from app.utils.web_search import web_search

logger = logging.getLogger(__name__)


class NoteChatIntent(BaseModel):
    """Intent classification for note chat messages."""

    intent: Literal["casual", "question", "research"] = Field(
        description="casual: greetings, thanks, acknowledgments. question: asking about the note content or source documents. research: explicit request to search the web for external information"
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


async def note_chat_pipeline(
    note_title: str,
    note_markdown: str,
    note_query: str | None,
    project_name: str,
    messages: list[ChatMessageHistory] | None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> AsyncGenerator[tuple[str, str | list | None], None]:
    """AI assistant chat about a note with document context.

    Yields tuples of (event_type, data):
    - ("token", token_string) — streamed response tokens
    - ("sources", source_list) — retrieved document chunks
    - ("web_sources", source_list) — web search results
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

    try:
        structured_llm = llm.with_structured_output(NoteChatIntent, method="json_schema")
        intent_result = await structured_llm.ainvoke([
            SystemMessage(content="""Classify the user's message into exactly one category:

CASUAL: greetings, thanks, short acknowledgments
- "hi", "hello", "thanks", "got it", "okay"

QUESTION: asking about the note content, source documents, or requesting explanations
- "what does the note say about X", "explain this part", "summarize the source documents"

RESEARCH: explicit request to search the web or look up external information
- "search the web", "find online", "look up", "what does the internet say"
- Any request that explicitly asks for web/online/external research

Only classify as RESEARCH if the user explicitly asks for web research. Otherwise, default to QUESTION."""),
            HumanMessage(content=latest_user_msg),
        ])
        detected_intent = intent_result.intent
    except Exception:
        logger.warning("Note chat intent classification failed, treating as question", exc_info=True)
        detected_intent = "question"

    all_messages = []
    if messages:
        for m in messages:
            if m.role == "user":
                all_messages.append(HumanMessage(content=m.content))
            else:
                all_messages.append(AIMessage(content=m.content))

    today = datetime.now(tz=UTC).strftime("%B %d, %Y")

    note_context = f'Note title: "{note_title}"'
    if note_query:
        note_context += f'\nOriginal query: "{note_query}"'
    note_context += f"\n\nPreviously generated summary:\n{note_markdown}"

    if detected_intent == "casual":
        system_prompt = f"""You are a friendly research assistant helping with a note. Today's date is {today}.

The user is having a conversation about this note:

{note_context}

{FORMAT_INSTRUCTIONS}
Respond naturally and conversationally. Keep it brief."""

        try:
            async for chunk in llm.astream([SystemMessage(content=system_prompt)] + all_messages):
                if chunk.content:
                    yield ("token", chunk.content)
            yield ("sources", [])
            yield ("done", None)
        except Exception as e:
            logger.exception("Note chat casual response failed")
            yield ("error", f"Failed to respond: {e}")
            yield ("done", None)
        return

    if detected_intent == "research":
        logger.info("note_chat: research intent detected, performing web search")
        try:
            search_query = f"{note_title} {latest_user_msg}"
            results = await web_search(search_query)
        except Exception:
            logger.exception("note_chat: web search failed")
            yield ("error", "Web search failed. Please try again.")
            yield ("done", None)
            return

        context_parts = []
        web_sources = []
        images = results.get("images", [])

        if results.get("answer"):
            context_parts.append(f"[Web Summary]\n{results['answer']}")

        for i, r in enumerate(results.get("results", []), 1):
            context_parts.append(
                f"[Source {i}: {r.get('title', 'Unknown')}]\n"
                f"URL: {r.get('url', '')}\n"
                f"{r.get('content', '')}"
            )
            web_sources.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "preview": r.get("content", "")[:300],
                "imageUrl": images[i - 1] if i - 1 < len(images) else None,
            })

        context = "\n\n---\n\n".join(context_parts)

        system_prompt = f"""You are a helpful research assistant. Today's date is {today}.

The user is asking about this note and requested external research:

{note_context}

User's research request: {latest_user_msg}

{FORMAT_INSTRUCTIONS}
Provide information based on the web search results below. Cite sources when possible.

Web search results:
{context}"""

        try:
            async for chunk in llm.astream([SystemMessage(content=system_prompt)] + all_messages):
                if chunk.content:
                    yield ("token", chunk.content)
            yield ("web_sources", web_sources)
            yield ("done", None)
        except Exception as e:
            logger.exception("Note chat research response failed")
            yield ("error", f"Failed to respond: {e}")
            yield ("done", None)
        return

    # Use note_markdown directly as context (no vector retrieval needed)
    system_prompt = f"""You are a helpful research assistant. Today's date is {today}.

The user is asking about this note:

{note_context}

{FORMAT_INSTRUCTIONS}
Answer the user's question using the note summary as your primary context.
If the note doesn't contain relevant information, say so explicitly.

Use the conversation history to maintain context."""

    try:
        async for chunk in llm.astream([SystemMessage(content=system_prompt)] + all_messages):
            if chunk.content:
                yield ("token", chunk.content)
        yield ("sources", [])
        yield ("done", None)
    except Exception as e:
        logger.exception("Note chat response failed")
        yield ("error", f"Failed to respond: {e}")
        yield ("done", None)
