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


class AssistantChatIntent(BaseModel):
    """Intent classification for assistant chat messages."""

    intent: Literal["casual", "question", "research"] = Field(
        description="casual: greetings, thanks, acknowledgments. question: asking about the context or source documents. research: explicit request to search the web for external information"
    )


FORMAT_INSTRUCTIONS = """When formatting your response:

Tables - Use proper markdown table syntax:
| Column 1 | Column 2 | Column 3 |
|----------|----------|----------|
| Data     | Data     | Data     |

Diagrams - Use ONLY valid Mermaid syntax in fenced code blocks:
```mermaid
graph TD
    A[Start] --> B[Process]
    B --> C[End]
```

Valid Mermaid types: graph TD, graph LR, sequenceDiagram, classDiagram, stateDiagram, flowchart
DO NOT use ASCII art or text sketches - they will not render.

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


def _extract_usage(chunk) -> dict | None:
    """Extract token usage from a LangChain response chunk."""
    usage = None
    if hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
        um = chunk.usage_metadata
        usage = {
            "input_tokens": getattr(um, "input_tokens", 0) or 0,
            "output_tokens": getattr(um, "output_tokens", 0) or 0,
            "total_tokens": getattr(um, "total_tokens", 0) or 0,
        }
    if not usage and hasattr(chunk, "response_metadata") and chunk.response_metadata:
        rm = chunk.response_metadata
        if "usage" in rm:
            u = rm["usage"]
            usage = {
                "input_tokens": u.get("prompt_tokens", 0) or u.get("input_tokens", 0),
                "output_tokens": u.get("completion_tokens", 0) or u.get("output_tokens", 0),
                "total_tokens": u.get("total_tokens", 0) or (u.get("prompt_tokens", 0) + u.get("completion_tokens", 0)),
            }
    return usage


async def _stream_llm(
    llm, messages: list
) -> AsyncGenerator[tuple[str, str | dict | None], None]:
    """Stream LLM response, yielding model_info, token, and usage events."""
    model_yielded = False
    last_usage = None
    async for chunk in llm.astream(messages):
        if not model_yielded:
            actual_model = None
            if hasattr(chunk, "response_metadata"):
                actual_model = chunk.response_metadata.get("model_name")
            if not actual_model and hasattr(chunk, "usage_metadata") and chunk.usage_metadata:
                actual_model = getattr(chunk.usage_metadata, "model", None)
            if actual_model:
                yield ("model_info", actual_model)
                model_yielded = True
        if chunk.content:
            yield ("token", chunk.content)
        usage = _extract_usage(chunk)
        if usage:
            last_usage = usage
    if last_usage:
        yield ("usage", last_usage)


def _build_intent_prompt(today: str, include_context_hint: bool = False) -> str:
    """System prompt for classifying user intent into casual/question/research."""
    question_desc = (
        "asking about the provided CONTEXT / SOURCE DOCUMENTS, or fixed knowledge\n"
        "- About the context: \"what does the context say about X\", \"explain this part\", \"summarize the source documents\"\n"
        "- Definitions / historical facts / scientific concepts that don't change over time\n"
        "- \"what is photosynthesis?\", \"when was WWII?\", \"how does gravity work?\""
        if include_context_hint
        else "fixed knowledge that doesn't change over time (definitions, historical facts, scientific concepts)\n"
        "- \"what is photosynthesis?\", \"who was Einstein?\", \"how does gravity work?\""
    )
    return f"""Classify the user's message into exactly one category. Respond in JSON: {{"intent": "casual"|"question"|"research"}}

CASUAL: greetings, thanks, short acknowledgments
- "hi", "hello", "thanks", "got it", "okay"

QUESTION: {question_desc}

RESEARCH: questions requiring CURRENT / REAL-TIME information, OR EXPLICIT web search
- Explicit requests: "search the web", "find online", "look up", "what does the internet say", "compare with external sources"
- Time-sensitive words: "today", "now", "current", "latest", "2026", "recent", "this week", "yesterday"
- Real-time data: weather, prices, availability, schedules, enrollment, openings
- Current state of entities: "does VAMK have a nursing program?", "is X available?", "current prices", "what programs does [institution] offer?"
- Current offerings / status of a specific institution, business or service
- News / current events: "latest news about", "what happened recently"

CRITICAL RULE: Use the TIME TEST — "Would the answer be DIFFERENT if asked in 2023 vs {today[:4]}?"
- YES (weather, programs, prices, availability, current events, schedules) → RESEARCH
- NO (definitions, historical facts, scientific concepts) → QUESTION

When in doubt: if the query is about a SPECIFIC entity (school, business, service, authority) and asks about current offerings, availability, requirements or status, choose RESEARCH because this information changes over time."""


async def _classify_intent(
    llm, latest_user_msg: str, today: str, include_context_hint: bool = False
) -> str:
    """Classify user intent via structured output. Falls back to keyword scan on error."""
    try:
        structured_llm = llm.with_structured_output(AssistantChatIntent, method="json_schema")
        intent_result = await structured_llm.ainvoke([
            SystemMessage(content=_build_intent_prompt(today, include_context_hint)),
            HumanMessage(content=latest_user_msg),
        ])
        return intent_result.intent
    except Exception:
        logger.warning("Assistant chat intent classification failed, falling back to keywords", exc_info=True)
        msg_lower = latest_user_msg.lower()
        research_keywords = ["search the web", "find online", "look up", "what does the internet say", "search online", "google"]
        if any(kw in msg_lower for kw in research_keywords):
            return "research"
        return "question"


async def assistant_chat_pipeline(
    context_title: str,
    context_content: str,
    project_name: str,
    messages: list[ChatMessageHistory] | None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    context_query: str | None = None,
    system_prompt_override: str | None = None,
    skip_context: bool = False,
) -> AsyncGenerator[tuple[str, str | list | dict | None], None]:
    """Generic AI assistant chat with optional context.

    Yields tuples of (event_type, data):
    - ("token", token_string) — streamed response tokens
    - ("sources", source_list) — retrieved document chunks
    - ("web_sources", source_list) — web search results
    - ("model_info", model_name) — actual model used
    - ("usage", usage_dict) — token usage stats
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

    all_messages = []
    if messages:
        for m in messages:
            if m.role == "user":
                all_messages.append(HumanMessage(content=m.content))
            else:
                all_messages.append(AIMessage(content=m.content))

    today = datetime.now(tz=UTC).strftime("%B %d, %Y")

    if skip_context:
        async for event_type, data in _handle_skip_context(llm, all_messages, latest_user_msg, today):
            yield (event_type, data)
        return

    detected_intent = await _classify_intent(llm, latest_user_msg, today, include_context_hint=True)

    context_block = f'Context title: "{context_title}"'
    if context_query:
        context_block += f'\nOriginal query: "{context_query}"'
    context_block += f"\n\nContext content:\n{context_content}"

    if detected_intent == "casual":
        system_prompt = system_prompt_override or f"""You are a friendly research assistant. Today's date is {today}.

The user is having a conversation about this context:

{context_block}

{FORMAT_INSTRUCTIONS}
Respond naturally and conversationally. Keep it brief."""

        try:
            async for event_type, data in _stream_llm(llm, [SystemMessage(content=system_prompt)] + all_messages):
                yield (event_type, data)
            yield ("sources", [])
            yield ("done", None)
        except Exception as e:
            logger.exception("Assistant chat casual response failed")
            yield ("error", f"Failed to respond: {e}")
            yield ("done", None)
        return

    if detected_intent == "research":
        logger.info("assistant_chat: research intent detected, performing web search")
        try:
            search_query = f"{context_title} {latest_user_msg}"
            results = await web_search(search_query)
        except Exception:
            logger.exception("assistant_chat: web search failed")
            yield ("error", "Web search failed. Please try again.")
            yield ("done", None)
            return

        web_sources = _build_web_sources(results)
        context = _build_web_context(results)

        system_prompt = system_prompt_override or f"""You are a helpful research assistant. Today's date is {today}.

The user is asking about this context and requested external research:

{context_block}

User's research request: {latest_user_msg}

{FORMAT_INSTRUCTIONS}
Provide information based on the web search results below. Cite sources when possible.

Web search results:
{context}"""

        try:
            async for event_type, data in _stream_llm(llm, [SystemMessage(content=system_prompt)] + all_messages):
                yield (event_type, data)
            yield ("web_sources", web_sources)
            yield ("done", None)
        except Exception as e:
            logger.exception("Assistant chat research response failed")
            yield ("error", f"Failed to respond: {e}")
            yield ("done", None)
        return

    system_prompt = system_prompt_override or f"""You are a helpful research assistant. Today's date is {today}.

The user is asking about this context:

{context_block}

{FORMAT_INSTRUCTIONS}
Answer the user's question using the context as your primary source.
If the context doesn't contain relevant information, say so explicitly.

Use the conversation history to maintain context."""

    try:
        async for event_type, data in _stream_llm(llm, [SystemMessage(content=system_prompt)] + all_messages):
            yield (event_type, data)
        yield ("sources", [])
        yield ("done", None)
    except Exception as e:
        logger.exception("Assistant chat question response failed")
        yield ("error", f"Failed to respond: {e}")
        yield ("done", None)


def _build_web_sources(results: dict) -> list[dict]:
    """Build web source objects from search results."""
    web_sources = []
    images = results.get("images", [])
    for i, r in enumerate(results.get("results", []), 1):
        web_sources.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "preview": r.get("content", "")[:300],
            "imageUrl": images[i - 1] if i - 1 < len(images) else None,
        })
    return web_sources


def _build_web_context(results: dict) -> str:
    """Build context string from web search results."""
    context_parts = []
    if results.get("answer"):
        context_parts.append(f"[Web Summary]\n{results['answer']}")
    for i, r in enumerate(results.get("results", []), 1):
        context_parts.append(
            f"[Source {i}: {r.get('title', 'Unknown')}]\n"
            f"URL: {r.get('url', '')}\n"
            f"{r.get('content', '')}"
        )
    return "\n\n---\n\n".join(context_parts)


async def _handle_skip_context(
    llm, all_messages: list, latest_user_msg: str, today: str
) -> AsyncGenerator[tuple[str, str | list | dict | None], None]:
    """Handle plain LLM chat without document context — supports web search."""
    detected_intent = await _classify_intent(llm, latest_user_msg, today, include_context_hint=False)
    is_research = detected_intent == "research"

    if is_research:
        logger.info("assistant_chat skip_context: research intent, performing web search")
        try:
            results = await web_search(latest_user_msg)
        except Exception:
            logger.exception("assistant_chat: web search failed")
            yield ("error", "Web search failed. Please try again.")
            yield ("done", None)
            return

        web_sources = _build_web_sources(results)
        context = _build_web_context(results)

        system_prompt = f"""You are a helpful research assistant. Today's date is {today}.

{FORMAT_INSTRUCTIONS}
Provide information based on the web search results below. Cite sources when possible.

User's request: {latest_user_msg}

Web search results:
{context}"""

        try:
            async for event_type, data in _stream_llm(llm, [SystemMessage(content=system_prompt)] + all_messages):
                yield (event_type, data)
            yield ("web_sources", web_sources)
            yield ("done", None)
        except Exception as e:
            logger.exception("Assistant chat research response failed")
            yield ("error", f"Failed to respond: {e}")
            yield ("done", None)
        return

    system_prompt = f"""You are a helpful AI assistant. Today's date is {today}.

{FORMAT_INSTRUCTIONS}
Answer the user's question clearly and helpfully."""

    try:
        async for event_type, data in _stream_llm(llm, [SystemMessage(content=system_prompt)] + all_messages):
            yield (event_type, data)
        yield ("sources", [])
        yield ("done", None)
    except Exception as e:
        logger.exception("Assistant chat skip_context response failed")
        yield ("error", f"Failed to respond: {e}")
        yield ("done", None)
