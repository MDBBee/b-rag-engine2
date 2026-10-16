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
    intent: Literal["casual", "summary", "specific"] = Field(
        description="casual: greetings/chat, summary: overview/main points, specific: targeted question"
    )


class RAGState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    current_query: str
    intent: str
    context: str
    collection_name: str
    user_id: str
    project_name: str
    file_name: str
    retrieved_docs: list
    llm: object
    top_k: int
    retry_count: int
    max_retries: int


async def classify_intent(state: RAGState) -> dict:
    """Classify query intent using structured output."""
    query = state["current_query"]
    llm = state["llm"]

    try:
        structured_llm = llm.with_structured_output(IntentDecision, method="json_schema")
        result = await structured_llm.ainvoke([
            SystemMessage(content="""Classify the user's query:

CASUAL: greetings, thanks, general chat, time/date questions, meta-questions about the assistant
- Examples: "hi", "hello", "how are you", "what's today's date", "thanks", "good morning"

SUMMARY: requests for overview, main points, comprehensive coverage
- Examples: "summarize this", "give me an overview", "what are the main points", "what's in this document"

SPECIFIC: targeted question about document content or concepts
- Examples: "what does X mean", "explain the methodology", "tell me about the author's argument"

IMPORTANT: If the query asks for ANY kind of overview or comprehensive coverage, classify as SUMMARY. When in doubt between summary and specific, choose SPECIFIC."""),
            HumanMessage(content=query),
        ])

        if result is None:
            return {"intent": "specific"}

        return {"intent": result.intent}

    except Exception as e:
        model_name = getattr(llm, 'model', 'unknown')
        raise ValueError(
            f"Model selected: {model_name}, does not support tool and/or function calling, please pick another!"
        ) from e


async def retrieve_all(state: RAGState) -> dict:
    """Retrieve all chunks in document order for summaries."""
    collection_name = state.get("collection_name", "default")
    user_id = state.get("user_id", "")
    max_chunks = settings.max_context_chunks

    cursor = mongodb.vectors.find(
        {"user_id": user_id, "collection_name": collection_name}
    ).sort("chunk_index", 1).limit(max_chunks)

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
    collection_name = state.get("collection_name", "default")
    top_k = state.get("top_k", settings.top_k)

    pre_filter = {"user_id": user_id, "collection_name": collection_name}
    docs = await mongodb.vectorstore.asimilarity_search(query, k=top_k, pre_filter=pre_filter)

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

    response = await llm.ainvoke([
        SystemMessage(content="Rephrase this query to improve retrieval. Use different keywords or synonyms. Return ONLY the rephrased query, no explanation."),
        HumanMessage(content=query)
    ])

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

When creating markdown tables, ensure each row is on its own line with proper formatting. Example:
| Column 1 | Column 2 |
|----------|----------|
| Data 1   | Data 2   |"""

    llm_messages = [SystemMessage(content=system_prompt)] + messages

    response = await llm.ainvoke(llm_messages)
    return {"messages": [response]}


async def generate(state: RAGState) -> dict:
    """Generate answer with document context."""
    intent = state["intent"]
    messages = state["messages"]
    project_name = state.get("project_name", "")
    file_name = state.get("file_name", "")
    llm = state["llm"]
    today = datetime.now(tz=UTC).strftime("%B %d, %Y")

    context_prefix = ""
    if project_name or file_name:
        parts = []
        if project_name:
            parts.append(f'project "{project_name}"')
        if file_name:
            parts.append(f'document "{file_name}"')
        context_prefix = f"You are assisting with {' and '.join(parts)}. Today's date is {today}. "

    if intent == "summary":
        system_prompt = f"""{context_prefix}You are a helpful research assistant. Provide a comprehensive summary based on the full document content provided below. Cover all major topics and key points in a well-structured manner.

Guidelines:
- Use the full document context to create a thorough summary
- Organize the summary logically, covering all sections
- Be conversational and natural, not robotic
- When creating markdown tables, ensure each row is on its own line with proper formatting

Context:
{state['context']}"""
    else:
        system_prompt = f"""{context_prefix}You are a helpful research assistant. Answer questions based on the provided document context and conversation history.

Guidelines:
- Use the document context to answer questions about the documents
- Use conversation history to remember what the user has told you
- If the context doesn't contain relevant information, you can answer from general knowledge
- Be conversational and natural, not robotic
- When creating markdown tables, ensure each row is on its own line with proper formatting. Example:
| Column 1 | Column 2 |
|----------|----------|
| Data 1   | Data 2   |

Context:
{state['context']}"""

    llm_messages = [SystemMessage(content=system_prompt)] + messages

    response = await llm.ainvoke(llm_messages)
    return {"messages": [response]}


def intent_router(state: RAGState) -> Literal["generate_direct", "retrieve_all", "retrieve_top_k"]:
    """Route based on classified intent."""
    intent = state["intent"]
    if intent == "casual":
        return "generate_direct"
    elif intent == "summary":
        return "retrieve_all"
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

    graph.add_edge(START, "classify_intent")
    graph.add_conditional_edges("classify_intent", intent_router, ["generate_direct", "retrieve_all", "retrieve_top_k"])
    graph.add_edge("retrieve_all", "generate")
    graph.add_edge("generate_direct", END)

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
    collection_name: str,
    user_id: str,
    messages: list[ChatMessageHistory] | None = None,
    project_name: str | None = None,
    file_name: str | None = None,
    top_k: int | None = None,
    max_retries: int | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> AsyncGenerator[tuple[str, str | list[dict]], None]:
    """Stream RAG response with conversation history from frontend."""
    all_messages = [m.model_dump() for m in messages] + [{"role": "user", "content": query}]

    resolved_provider = llm_provider or "openrouter"

    if resolved_provider == "ollama":
        if not llm_model:
            yield ("error", "Ollama provider selected but no model specified. Please select a model in project settings.")
            yield ("done", None)
            return
        llm = mongodb.get_llm(llm_model)
    else:
        llm = mongodb.llm

    rag_pipeline = get_compiled_graph()

    input_data = {
        "messages": all_messages,
        "current_query": query,
        "retry_count": 0,
        "max_retries": max_retries if max_retries is not None else settings.max_rephrase_retries,
        "collection_name": collection_name,
        "user_id": user_id,
        "project_name": project_name or "",
        "file_name": file_name or "",
        "llm": llm,
        "top_k": top_k or settings.top_k,
    }

    sources_yielded = False
    node_names = {"classify_intent", "retrieve_all", "retrieve_top_k", "rephrase_query", "generate_direct", "generate"}

    try:
        async for event in rag_pipeline.astream_events(
            input_data,
            version="v2",
        ):
            event_type = event["event"]
            metadata = event.get("metadata", {})
            node_name = metadata.get("langgraph_node")

            if event_type == "on_chain_start" and node_name in node_names:
                yield ("node_start", node_name)

            elif event_type == "on_chat_model_stream":
                if node_name in ("generate", "generate_direct"):
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
    except ValueError as e:
        yield ("error", str(e))
        yield ("done", None)
        return

    if not sources_yielded:
        yield ("sources", [])

    yield ("done", None)
