import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from app.config import settings
from app.typing.schemas import ChatMessageHistory
from app.utils import mongodb
from app.utils.web_search import web_search

logger = logging.getLogger(__name__)

compiled_graph = None
cached_rephrase_enabled = None


def init_graph():
    """Initialize graph at app startup."""
    global compiled_graph, cached_rephrase_enabled
    compiled_graph = build_graph()
    cached_rephrase_enabled = settings.rephrase_enabled


def get_compiled_graph():
    """Get cached graph, rebuild only if settings changed."""
    if compiled_graph is None or cached_rephrase_enabled != settings.rephrase_enabled:
        init_graph()
    return compiled_graph


class IntentDecision(BaseModel):
    """Classification of query intent."""
    intent: Literal["casual", "summary", "specific", "research"] = Field(
        description="casual: greetings/chat, summary: overview/main points, specific: targeted question, research: explicit request for web search"
    )


class RAGState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    current_query: str
    intent: str
    context: str
    project_name: str
    user_id: str
    file_name: str
    retrieved_docs: list
    llm: object
    top_k: int
    summary_chunks: int | None
    retry_count: int
    max_retries: int
    file_scope: list[str] | None
    embedding_model: str | None
    usage_metadata: dict | None
    web_sources: list[dict] | None


async def classify_intent(state: RAGState) -> dict:
    """Classify query intent using structured output."""
    query = state["current_query"]
    llm = state["llm"]

    try:
        logger.info(
            "classify_intent: model=%s, query_length=%d, query_preview=%s",
            getattr(llm, 'model', 'unknown'),
            len(query),
            query[:100].replace('\n', ' ')
        )
        
        structured_llm = llm.with_structured_output(IntentDecision, method="json_mode")
        logger.info("classify_intent: invoking structured LLM with json_mode...")
        
        result = await structured_llm.ainvoke([
            SystemMessage(content="""Classify the user's query into exactly one category. Respond in JSON: {"intent": "casual"|"summary"|"specific"|"research"}

CASUAL: greetings, thanks, conversational chat
- "hi", "hello", "thanks", "how are you", "good morning"

SUMMARY: requests to summarize UPLOADED DOCUMENTS
- "summarize the document", "overview of the files", "main points", "what's in this document"

SPECIFIC: questions about UPLOADED DOCUMENTS or STATIC knowledge (unchanging facts)
- Document content: "what does the thesis say about X?", "explain the methodology from the document"
- Definitions: "what is photosynthesis?", "explain quantum mechanics"
- Historical facts: "when was WWII?", "who was Einstein?"
- Scientific concepts: "how does gravity work?", "what is pi?"
- Fixed knowledge that doesn't change over time

RESEARCH: questions requiring CURRENT/REAL-TIME information or EXPLICIT web search
- Explicit requests: "search the web", "find online", "look up", "what does the internet say", "compare with external sources"
- Time-sensitive words: "today", "now", "current", "latest", "2026", "recent", "this week", "yesterday"
- Real-time data: weather, stock prices, sports scores, availability, schedules, enrollment
- Current state of entities: "does VAMK have a nursing program?", "is X available?", "current prices", "enrollment deadlines", "what programs does [institution] offer?"
- News/current events: "latest news about", "what happened recently", "who won the game"

CRITICAL RULE: Use the TIME TEST - "Would the answer be DIFFERENT if asked in 2023 vs 2026?"
- YES (weather, programs, prices, availability, current events, schedules) → RESEARCH
- NO (definitions, historical facts, scientific concepts) → SPECIFIC

When in doubt: if the query is about a SPECIFIC entity (school, business, service) and asks about current offerings/availability/status, choose RESEARCH because this information changes over time."""),
            HumanMessage(content=query),
        ])

        logger.info("classify_intent: success, intent=%s", getattr(result, 'intent', 'unknown'))

        if result is None:
            return {"intent": "specific"}

        return {"intent": result.intent}

    except Exception as e:
        model_name = getattr(llm, 'model', 'unknown')
        error_type = type(e).__name__
        error_msg = str(e)
        
        logger.error(
            "classify_intent failed: model=%s, error_type=%s, error_msg=%s",
            model_name, error_type, error_msg,
        )
        
        # Extract OpenAI/HTTP error details
        if hasattr(e, 'status_code'):
            logger.error("classify_intent: HTTP status=%s", e.status_code)
        if hasattr(e, 'response'):
            response_text = e.response.text if hasattr(e.response, 'text') else str(e.response)
            logger.error("classify_intent: response_body=%s", response_text)
        if hasattr(e, 'body'):
            logger.error("classify_intent: error_body=%s", e.body)
        
        raise ValueError(
            f"Model '{model_name}' failed: {error_type} - {error_msg}"
        ) from e


async def retrieve_all(state: RAGState) -> dict:
    """Retrieve all chunks in document order for summaries."""
    project_name = state.get("project_name", "default")
    user_id = state.get("user_id", "")
    max_chunks = state.get("summary_chunks") or settings.max_context_chunks
    file_scope = state.get("file_scope")

    filter_query = {"user_id": user_id, "project_name": project_name}
    if file_scope:
        filter_query["metadata.source"] = {"$in": file_scope}

    cursor = mongodb.vectors.find(filter_query).sort("chunk_index", 1).limit(max_chunks)

    docs = []
    async for doc in cursor:
        docs.append(doc)

    if not docs:
        return {"context": "", "retrieved_docs": []}

    context_parts = []
    for i, doc in enumerate(docs, 1):
        source = doc.get("metadata", {}).get("source", "Unknown")
        chunk_idx = doc.get("metadata", {}).get("chunk_index", i)
        context_parts.append(f"[Source: {source}, chunk {chunk_idx}]\n{doc.get('content', '')}")

    context = "\n\n" + "=" * 60 + "\n\n".join(context_parts)
    return {"context": context, "retrieved_docs": docs}


async def retrieve_top_k(state: RAGState) -> dict:
    """Retrieve relevant documents from vector store."""
    query = state.get("current_query") or state["messages"][-1].content
    user_id = state.get("user_id", "")
    project_name = state.get("project_name", "default")
    top_k = state.get("top_k", settings.top_k)
    file_scope = state.get("file_scope")
    embedding_model = state.get("embedding_model")

    pre_filter = {"user_id": user_id, "project_name": project_name}
    if file_scope:
        pre_filter["metadata.source"] = {"$in": file_scope}

    vectorstore = mongodb.get_vectorstore(embedding_model)
    docs = await vectorstore.asimilarity_search(query, k=top_k, pre_filter=pre_filter)

    if not docs:
        return {"context": "", "retrieved_docs": []}

    context_parts = []
    for i, doc in enumerate(docs, 1):
        source = doc.metadata.get("source", "Unknown")
        chunk_idx = doc.metadata.get("chunk_index", "N/A")
        context_parts.append(f"[Source: {source}, chunk {chunk_idx}]\n{doc.page_content}")

    context = "\n\n" + "=" * 60 + "\n\n".join(context_parts)
    return {"context": context, "retrieved_docs": docs}


async def rephrase_query_node(state: RAGState) -> dict:
    """Rephrase the query to improve retrieval results."""
    query = state.get("current_query") or state["messages"][-1].content
    retry_count = state.get("retry_count", 0)
    llm = state["llm"]

    logger.info(
        "rephrase_query: model=%s, query_length=%d, retry=%d",
        getattr(llm, 'model', 'unknown'), len(query), retry_count
    )

    try:
        response = await llm.ainvoke([
            SystemMessage(content="Rephrase this query to improve retrieval. Use different keywords or synonyms. Return ONLY the rephrased query, no explanation."),
            HumanMessage(content=query)
        ])
        logger.info("rephrase_query: success, rephrased_length=%d", len(response.content))
    except Exception as e:
        logger.exception("rephrase_query failed: model=%s", getattr(llm, 'model', 'unknown'))
        if hasattr(e, 'status_code'):
            logger.error("rephrase_query: HTTP status=%s", e.status_code)
        if hasattr(e, 'body'):
            logger.error("rephrase_query: error_body=%s", e.body)
        raise

    return {
        "current_query": response.content.strip(),
        "retry_count": retry_count + 1
    }


async def generate_direct(state: RAGState) -> dict:
    """Generate casual response without document context."""
    messages = state["messages"]
    llm = state["llm"]
    today = datetime.now(tz=UTC).strftime("%B %d, %Y")

    system_prompt = f"""You are a friendly research assistant. Today's date is {today}. Engage naturally in conversation.

Do NOT include:
- Apologies, filler phrases, or hedging before answering ("Thank you", "I apologize", "You're correct, and...")
- Placeholder letters (A, B, C, D) in tables — if data is unavailable, write "Data not available"

When formatting your response:

Tables - Use proper markdown table syntax:
| Column 1 | Column 2 | Column 3 |
|----------|----------|----------|
| Data     | Data     | Data     |

Lists - Use markdown list syntax:
- Item 1
- Item 2
- Item 3

Code - Use fenced code blocks with language tags:
```python
def example():
    return "code"
```

Never concatenate multiple lines together. Keep cells concise (under 20 words).
"""

    llm_messages = [SystemMessage(content=system_prompt)] + messages

    total_length = sum(len(str(m.content)) for m in llm_messages)
    logger.info(
        "generate_direct: model=%s, message_count=%d, total_length=%d",
        getattr(llm, 'model', 'unknown'), len(llm_messages), total_length
    )

    try:
        response = await llm.ainvoke(llm_messages)
        logger.info("generate_direct: success, response_length=%d", len(response.content))
        
        # Extract token usage from response
        usage_metadata = getattr(response, 'usage_metadata', None)
        if usage_metadata:
            logger.info("generate_direct: token_usage=%s", usage_metadata)
    except Exception as e:
        logger.exception("generate_direct failed: model=%s", getattr(llm, 'model', 'unknown'))
        if hasattr(e, 'status_code'):
            logger.error("generate_direct: HTTP status=%s", e.status_code)
        if hasattr(e, 'body'):
            logger.error("generate_direct: error_body=%s", e.body)
        raise

    return {"messages": [response], "usage_metadata": usage_metadata}


async def web_research(state: RAGState) -> dict:
    """Perform web search via Tavily."""
    query = state.get("current_query") or state["messages"][-1].content
    logger.info("web_research: query=%s", query[:100])

    try:
        results = await web_search(query)
    except Exception:
        logger.exception("web_research failed")
        return {"context": "", "web_sources": []}

    context_parts = []
    web_sources = []

    if results.get("answer"):
        context_parts.append(f"[Web Summary]\n{results['answer']}")

    images = results.get("images", [])

    for i, r in enumerate(results.get("results", []), 1):
        context_parts.append(
            f"[Source {i}: {r.get('title', 'Unknown')}]\n"
            f"URL: {r.get('url', '')}\n"
            f"{r.get('content', '')}"
        )
        web_sources.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "preview": r.get("content", "")[:200],
            "imageUrl": images[i - 1] if i - 1 < len(images) else None,
        })

    return {
        "context": "\n\n---\n\n".join(context_parts),
        "retrieved_docs": [],
        "web_sources": web_sources,
    }


async def generate_with_web_context(state: RAGState) -> dict:
    """Generate answer using web search results."""
    messages = state["messages"]
    llm = state["llm"]
    today = datetime.now(tz=UTC).strftime("%B %d, %Y")

    system_prompt = f"""You are a helpful research assistant. Today's date is {today}.
Provide a comprehensive answer based on the web search results below.

Guidelines:
- Cite sources by title or URL when referencing specific information
- If images were found, mention them as available references
- Organize information logically with markdown formatting
- Use tables, lists, and code blocks as appropriate
- Do NOT include apologies, filler phrases, or hedging
- Do NOT use placeholder letters (A, B, C, D) in tables — write "Data not available" if unknown

Web Search Results:
{state['context']}"""

    llm_messages = [SystemMessage(content=system_prompt)] + messages

    total_length = sum(len(str(m.content)) for m in llm_messages)
    logger.info(
        "generate_with_web_context: model=%s, message_count=%d, total_length=%d, context_length=%d",
        getattr(llm, 'model', 'unknown'), len(llm_messages), total_length, len(state['context'])
    )

    try:
        response = await llm.ainvoke(llm_messages)
        logger.info("generate_with_web_context: success, response_length=%d", len(response.content))
        usage_metadata = getattr(response, 'usage_metadata', None)
        if usage_metadata:
            logger.info("generate_with_web_context: token_usage=%s", usage_metadata)
    except Exception as e:
        logger.exception("generate_with_web_context failed: model=%s", getattr(llm, 'model', 'unknown'))
        if hasattr(e, 'status_code'):
            logger.error("generate_with_web_context: HTTP status=%s", e.status_code)
        if hasattr(e, 'body'):
            logger.error("generate_with_web_context: error_body=%s", e.body)
        raise

    return {"messages": [response], "usage_metadata": usage_metadata}


async def generate(state: RAGState) -> dict:
    """Generate answer with document context."""
    intent = state["intent"]
    messages = state["messages"]
    project_name = state.get("project_name", "")
    file_name = state.get("file_name", "")
    llm = state["llm"]
    today = datetime.now(tz=UTC).strftime("%B %d, %Y")

    context_prefix = ""
    file_scope = state.get("file_scope")
    doc_label = ""
    if file_scope and len(file_scope) == 1:
        doc_label = f'document "{file_scope[0]}"'
    elif file_scope and len(file_scope) > 1:
        names = ", ".join(f'"{f}"' for f in file_scope)
        doc_label = f"documents {names}"
    elif file_name:
        doc_label = f'document "{file_name}"'

    if project_name or doc_label:
        parts = []
        if project_name:
            parts.append(f'project "{project_name}"')
        if doc_label:
            parts.append(doc_label)
        context_prefix = f"You are assisting with {' and '.join(parts)}. Today's date is {today}. "

    if intent == "summary":
        system_prompt = f"""{context_prefix}You are a helpful research assistant. Provide a comprehensive summary based on the full document content provided below. Cover all major topics and key points in a well-structured manner.

Guidelines:
- Use the full document context to create a thorough summary
- Organize the summary logically, covering all sections
- Do NOT include apologies, filler phrases, or hedging
- Do NOT use placeholder letters (A, B, C, D) in tables — write "Data not available" if unknown
- When formatting tables, use proper markdown syntax:
| Column 1 | Column 2 |
|----------|----------|
| Data     | Data     |
- For lists, use: - Item 1\n- Item 2
- For code, use fenced blocks with language tags
- Never concatenate multiple lines together

Context:
{state['context']}"""
    else:
        system_prompt = f"""{context_prefix}You are a helpful research assistant. Answer questions based on the provided document context and conversation history.

Guidelines:
- Use the document context to answer questions about the documents
- Use conversation history to remember what the user has told you
- If the context doesn't contain relevant information, you can answer from general knowledge
- Do NOT include apologies, filler phrases, or hedging
- Do NOT use placeholder letters (A, B, C, D) in tables — write "Data not available" if unknown
- When formatting tables, use proper markdown syntax:
| Column 1 | Column 2 |
|----------|----------|
| Data     | Data     |
- For lists, use: - Item 1\n- Item 2
- For code, use fenced blocks with language tags
- Never concatenate multiple lines together

Context:
{state['context']}"""

    llm_messages = [SystemMessage(content=system_prompt)] + messages

    total_length = sum(len(str(m.content)) for m in llm_messages)
    logger.info(
        "generate: model=%s, intent=%s, message_count=%d, total_length=%d, context_length=%d",
        getattr(llm, 'model', 'unknown'), intent, len(llm_messages), total_length, len(state['context'])
    )

    try:
        response = await llm.ainvoke(llm_messages)
        logger.info("generate: success, response_length=%d", len(response.content))
        
        # Extract token usage from response
        usage_metadata = getattr(response, 'usage_metadata', None)
        if usage_metadata:
            logger.info("generate: token_usage=%s", usage_metadata)
    except Exception as e:
        logger.exception("generate failed: model=%s, intent=%s", getattr(llm, 'model', 'unknown'), intent)
        if hasattr(e, 'status_code'):
            logger.error("generate: HTTP status=%s", e.status_code)
        if hasattr(e, 'body'):
            logger.error("generate: error_body=%s", e.body)
        raise

    return {"messages": [response], "usage_metadata": usage_metadata}


def intent_router(state: RAGState) -> Literal["generate_direct", "retrieve_all", "retrieve_top_k", "web_research"]:
    """Route based on classified intent."""
    intent = state["intent"]
    if intent == "casual":
        return "generate_direct"
    elif intent == "summary":
        return "retrieve_all"
    elif intent == "research":
        return "web_research"
    return "retrieve_top_k"


def post_retrieve_decision(state: RAGState) -> Literal["generate", "rephrase_query"]:
    """Generate if docs found or max retries reached, otherwise rephrase."""
    retrieved_docs = state.get("retrieved_docs", [])
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 1)

    if retrieved_docs or retry_count >= max_retries:
        return "generate"
    return "rephrase_query"


def build_graph():
    """Build and compile the RAG graph."""
    graph = StateGraph(RAGState)
    graph.add_node("classify_intent", classify_intent)
    graph.add_node("generate_direct", generate_direct)
    graph.add_node("retrieve_all", retrieve_all)
    graph.add_node("retrieve_top_k", retrieve_top_k)
    graph.add_node("generate", generate)
    graph.add_node("web_research", web_research)
    graph.add_node("generate_with_web_context", generate_with_web_context)

    graph.add_edge(START, "classify_intent")
    graph.add_conditional_edges("classify_intent", intent_router, ["generate_direct", "retrieve_all", "retrieve_top_k", "web_research"])
    graph.add_edge("retrieve_all", "generate")
    graph.add_edge("generate_direct", END)
    graph.add_edge("web_research", "generate_with_web_context")
    graph.add_edge("generate_with_web_context", END)

    if settings.rephrase_enabled:
        graph.add_node("rephrase_query", rephrase_query_node)
        graph.add_conditional_edges("retrieve_top_k", post_retrieve_decision, ["generate", "rephrase_query"])
        graph.add_edge("rephrase_query", "retrieve_top_k")
    else:
        graph.add_edge("retrieve_top_k", "generate")

    graph.add_edge("generate", END)

    return graph.compile()


async def retrieval_pipeline(
    query: str,
    project_name: str,
    user_id: str,
    messages: list[ChatMessageHistory] | None = None,
    file_name: str | None = None,
    top_k: int | None = None,
    summary_chunks: int | None = None,
    max_retries: int | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    file_scope: list[str] | None = None,
    embedding_model: str | None = None,
) -> AsyncGenerator[tuple[str, str | list[dict]], None]:
    """Stream RAG response with conversation history from frontend."""
    all_messages = [m.model_dump() for m in messages] + [{"role": "user", "content": query}]

    resolved_provider = llm_provider or "openrouter"
    resolved_model = llm_model or settings.llm_model

    logger.info(
        "retrieval_pipeline START: query_length=%d, project=%s, provider=%s, model=%s, "
        "top_k=%s, summary_chunks=%s, max_retries=%s, history_messages=%d, file_scope=%s",
        len(query), project_name, resolved_provider, resolved_model,
        top_k, summary_chunks, max_retries, len(messages or []), file_scope
    )

    if resolved_provider == "ollama":
        if not llm_model:
            yield ("error", "Ollama provider selected but no model specified. Please select a model in project settings.")
            yield ("done", None)
            return
        llm = mongodb.get_llm(llm_model)
    else:
        try:
            llm = mongodb.get_openrouter_llm(resolved_model)
            logger.info(
                "retrieval_pipeline: OpenRouter LLM created, model=%s, base_url=%s",
                resolved_model, settings.openrouter_base_url
            )
        except ValueError as e:
            logger.error("retrieval_pipeline: failed to create LLM - %s", str(e))
            yield ("error", str(e))
            yield ("done", None)
            return

    rag_pipeline = get_compiled_graph()

    input_data = {
        "messages": all_messages,
        "current_query": query,
        "retry_count": 0,
        "max_retries": max_retries if max_retries is not None else settings.max_rephrase_retries,
        "project_name": project_name,
        "user_id": user_id,
        "file_name": file_name or "",
        "llm": llm,
        "top_k": top_k or settings.top_k,
        "summary_chunks": summary_chunks,
        "file_scope": file_scope,
        "embedding_model": embedding_model,
        "usage_metadata": None,
        "web_sources": None,
    }

    sources_yielded = False
    node_names = {"classify_intent", "retrieve_all", "retrieve_top_k", "rephrase_query", "generate_direct", "generate", "web_research", "generate_with_web_context"}

    try:
        async for event in rag_pipeline.astream_events(
            input_data,
            version="v2",
        ):
            event_type = event["event"]
            metadata = event.get("metadata", {})
            node_name = metadata.get("langgraph_node")

            if event_type == "on_chain_start" and node_name in node_names:
                logger.info("pipeline: entering node=%s", node_name)
                yield ("node_start", node_name)

            elif event_type == "on_chat_model_stream":
                if node_name in ("generate", "generate_direct", "generate_with_web_context"):
                    chunk = event["data"].get("chunk")
                    if chunk and chunk.content:
                        if not sources_yielded:
                            yield ("sources", [])
                            sources_yielded = True
                        yield ("token", chunk.content)

            elif event_type == "on_chain_end" and node_name in ("retrieve_all", "retrieve_top_k"):
                output = event.get("data", {}).get("output", {})

                if isinstance(output, dict):
                    retrieved_docs = output.get("retrieved_docs", [])
                    if retrieved_docs and not sources_yielded:
                        sources = []
                        for i, doc in enumerate(retrieved_docs):
                            if isinstance(doc, dict):
                                sources.append({
                                    "chunk_id": str(doc.get("metadata", {}).get("chunk_index", i)),
                                    "content_preview": doc.get("content", "")[:300],
                                    "source": doc.get("metadata", {}).get("source"),
                                })
                            else:
                                sources.append({
                                    "chunk_id": str(doc.metadata.get("chunk_index", i)),
                                    "content_preview": doc.page_content[:300],
                                    "source": doc.metadata.get("source"),
                                })
                        yield ("sources", sources)
                        sources_yielded = True

            elif event_type == "on_chain_end" and node_name == "web_research":
                output = event.get("data", {}).get("output", {})
                if isinstance(output, dict):
                    web_sources = output.get("web_sources", [])
                    if web_sources:
                        yield ("web_sources", web_sources)

            elif event_type == "on_chain_end" and node_name in ("generate", "generate_direct", "generate_with_web_context"):
                output = event.get("data", {}).get("output", {})
                if isinstance(output, dict):
                    usage_metadata = output.get("usage_metadata")
                    if usage_metadata:
                        yield ("usage", usage_metadata)
    except ValueError as e:
        logger.exception("retrieval_pipeline ValueError")
        yield ("error", str(e))
        yield ("done", None)
        return
    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        logger.exception(
            "retrieval_pipeline failed: error_type=%s, error_msg=%s",
            error_type, error_msg,
        )
        if hasattr(e, 'status_code'):
            logger.error("retrieval_pipeline: HTTP status=%s", e.status_code)
        if hasattr(e, 'body'):
            logger.error("retrieval_pipeline: error_body=%s", e.body)
        if hasattr(e, 'response'):
            response_text = e.response.text if hasattr(e.response, 'text') else str(e.response)
            logger.error("retrieval_pipeline: response_body=%s", response_text)
        yield ("error", f"LLM error: {error_type} - {error_msg[:200]}")
        yield ("done", None)
        return

    if not sources_yielded:
        yield ("sources", [])

    yield ("done", None)
