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

# Module-level cache for compiled graph
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


METADATA_PATTERNS = {
    "file_name": [
        "file name", "name of the doc", "document name", "what file", 
        "what document", "doc name", "filename"
    ],
    "project_name": [
        "project name", "what project", "project"
    ],
    "collection_name": [
        "collection name", "collection"
    ],
}


def check_metadata_query(query: str, file_name: str, project_name: str, collection_name: str) -> str | None:
    """Check if query is asking for metadata. Returns natural language answer or None."""
    query_lower = query.lower()
    
    for field, patterns in METADATA_PATTERNS.items():
        for pattern in patterns:
            if pattern in query_lower:
                value = locals().get(field)
                if value:
                    field_label = field.replace("_", " ")
                    return f"The {field_label} is {value}."
    
    return None


class RouteDecision(BaseModel):
    """Classification of whether document retrieval is needed."""
    needs_retrieval: bool = Field(description="True if question should be answered from uploaded documents")


class RAGState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    route: str
    context: str
    collection_name: str
    user_id: str
    project_name: str
    file_name: str
    retrieved_docs: list
    llm: object
    top_k: int
    current_query: str
    retry_count: int
    max_retries: int


async def route_node(state: RAGState) -> dict:
    """Classify query intent: needs document retrieval or direct answer."""
    messages = state["messages"]
    query = messages[-1].content if messages else ""
    llm = state["llm"]

    try:
        structured_llm = llm.with_structured_output(RouteDecision)

        result = await structured_llm.ainvoke([
            SystemMessage(content="""Determine if the user's question should be answered from their uploaded documents or answered directly.

TRUE (retrieve from documents) — ANY question that COULD be answered by the uploaded documents:
- Questions about document content, topics, concepts, or information
- Questions about document metadata: author, title, date, page count, file name, etc.
- Questions that reference "the document", "the file", "what I uploaded", "my documents"
- Questions about what's IN the documents: "does it mention...", "is there a section about..."
- Questions about document structure: "how many pages...", "what chapters..."
- Examples: "What does it say about X?", "Who is the author?", "When was it written?", "Does it mention AI?", "What are the main points?"

FALSE (answer directly, no retrieval) — ONLY these specific cases:
- Greetings: "hi", "hello", "hey", "good morning"
- Thanks/gratitude: "thanks", "thank you"
- Questions about the conversation itself: "what is my name?", "what was my last question?"
- Meta-questions about you (the AI): "who are you?", "what can you do?"
- Personal statements: "my name is X", "I am from Y"
- General knowledge COMPLETELY unrelated to documents: "what time is it?", "what's the weather?"

IMPORTANT: If the question could possibly relate to the uploaded documents in ANY way, choose TRUE. When in doubt, ALWAYS choose TRUE."""),
            HumanMessage(content=query),
        ])

        if result is None:
            model_name = getattr(llm, 'model', 'unknown')
            raise ValueError(f"Model '{model_name}' does not support tool/function calling")

        return {"route": "retrieve" if result.needs_retrieval else "direct"}
    
    except Exception as e:
        model_name = getattr(llm, 'model', 'unknown')
        raise ValueError(
            f"Model selected: {model_name}, does not support tool and/or function calling, please pick another!"
        ) from e


async def retrieve_node(state: RAGState) -> dict:
    """Retrieve relevant documents from vector store with deduplication."""
    query = state.get("current_query") or state["messages"][-1].content
    user_id = state.get("user_id", "")
    collection_name = state.get("collection_name", "default")
    top_k = state.get("top_k", settings.top_k)

    pre_filter = {"user_id": user_id, "collection_name": collection_name}
    docs = await mongodb.vectorstore.asimilarity_search(query, k=top_k * 2, pre_filter=pre_filter)

    if not docs:
        return {"context": "", "retrieved_docs": []}

    seen = set()
    unique_docs = []
    for doc in docs:
        source = doc.metadata.get("source", "Unknown")
        chunk_idx = doc.metadata.get("chunk_index", "N/A")
        key = (source, chunk_idx)
        if key not in seen:
            seen.add(key)
            unique_docs.append(doc)
            if len(unique_docs) >= top_k:
                break

    context_parts = []
    for i, doc in enumerate(unique_docs, 1):
        source = doc.metadata.get("source", "Unknown")
        chunk_idx = doc.metadata.get("chunk_index", "N/A")
        context_parts.append(f"[Source {i}: {source}, chunk {chunk_idx}]\n{doc.page_content}")

    context = "\n\n" + "=" * 60 + "\n\n".join(context_parts)
    return {"context": context, "retrieved_docs": unique_docs}


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


async def generate_node(state: RAGState) -> dict:
    """Generate answer using LLM."""
    route = state["route"]
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

    if route == "retrieve" and state.get("context"):
        system_prompt = f"""{context_prefix}You are a helpful research assistant. Answer questions based on the provided document context and conversation history.

Guidelines:
- Use the document context to answer questions about the documents
- Use conversation history to remember what the user has told you (their name, preferences, previous questions)
- If the context doesn't contain relevant information, you can answer from general knowledge or conversation history
- Be conversational and natural, not robotic

Context:
{state['context']}"""
    else:
        system_prompt = f"""{context_prefix}You are a friendly and helpful research assistant. You help users with their documents and engage in natural conversation.

Guidelines:
- Use conversation history to remember what the user has told you (their name, preferences, previous questions)
- Answer general knowledge questions naturally and helpfully
- Be conversational, warm, and engaging
- If asked about documents, suggest the user upload documents or ask specific questions about their topic"""

    llm_messages = [SystemMessage(content=system_prompt)] + messages

    response = await llm.ainvoke(llm_messages)
    return {"messages": [response]}


def route_decision(state: RAGState) -> Literal["retrieve", "generate"]:
    """Route to retrieve or generate based on classification."""
    return "retrieve" if state["route"] == "retrieve" else "generate"


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
    graph.add_node("router", route_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("generate", generate_node)
    
    if settings.rephrase_enabled:
        graph.add_node("rephrase_query", rephrase_query_node)
        graph.add_edge(START, "router")
        graph.add_conditional_edges("router", route_decision, ["retrieve", "generate"])
        graph.add_conditional_edges("retrieve", post_retrieve_decision, ["generate", "rephrase_query"])
        graph.add_edge("rephrase_query", "retrieve")
        graph.add_edge("generate", END)
    else:
        graph.add_edge(START, "router")
        graph.add_conditional_edges("router", route_decision, ["retrieve", "generate"])
        graph.add_edge("retrieve", "generate")
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
    
    # Fast-path: metadata queries (no graph needed)
    metadata_answer = check_metadata_query(
        query, 
        file_name or "", 
        project_name or "", 
        collection_name
    )
    if metadata_answer:
        yield ("sources", [])
        for char in metadata_answer:
            yield ("token", char)
        yield ("done", None)
        return
    
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
    node_names = {"router", "retrieve", "rephrase_query", "generate"}

    try:
        async for event in rag_pipeline.astream_events(
            input_data,
            version="v2",
        ):
            event_type = event["event"]
            metadata = event.get("metadata", {})
            node_name = metadata.get("langgraph_node")
            
            if event_type == "on_chain_start" and node_name in node_names:
                print(f"NODE----START::::===>>:::, {node_name}")
                yield ("node_start", node_name)

            elif event_type == "on_chat_model_stream":
                if node_name == "generate":
                    chunk = event["data"].get("chunk")
                    if chunk and chunk.content:
                        if not sources_yielded:
                            yield ("sources", [])
                            sources_yielded = True
                        yield ("token", chunk.content)

            elif event_type == "on_chain_end":
                if node_name == "retrieve":
                    output = event.get("data", {}).get("output", {})
                    print(f"NODE----RETRIEVE::::===>>:::, {output}")
                    
                    # Defensive check: output might not be a dict
                    if isinstance(output, dict):
                        retrieved_docs = output.get("retrieved_docs", [])
                        if retrieved_docs and not sources_yielded:
                            sources = [
                                {
                                    "chunk_id": str(doc.metadata.get("chunk_index", i)),
                                    "content_preview": doc.page_content[:300],
                                    "source": doc.metadata.get("source"),
                                }
                                for i, doc in enumerate(retrieved_docs)
                            ]
                            yield ("sources", sources)
                            sources_yielded = True
    except ValueError as e:
        yield ("error", str(e))
        yield ("done", None)
        return

    if not sources_yielded:
        yield ("sources", [])

    yield ("done", None)
