import json
import uuid
import aiosqlite
from pathlib import Path
from typing import AsyncGenerator, TypedDict, Annotated, Literal
from datetime import datetime

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_chroma import Chroma
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, BaseMessage

from app.config import settings


class RAGState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    route: str
    context: str
    collection_name: str


def _get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        openai_api_key=settings.openrouter_api_key,
        openai_api_base=settings.openrouter_base_url,
    )


def _get_vectorstore(collection_name: str) -> Chroma:
    return Chroma(
        collection_name=collection_name,
        embedding_function=_get_embeddings(),
        persist_directory=settings.chroma_persist_dir,
    )


def _get_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.llm_model,
        openai_api_key=settings.openrouter_api_key,
        openai_api_base=settings.openrouter_base_url,
        temperature=0,
    )


def _get_router_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.router_model,
        openai_api_key=settings.openrouter_api_key,
        openai_api_base=settings.openrouter_base_url,
        temperature=0,
    )


async def route_node(state: RAGState) -> dict:
    """Classify query intent: needs document retrieval or direct answer."""
    last_message = state["messages"][-1]
    query = last_message.content if hasattr(last_message, "content") else str(last_message)

    router_llm = _get_router_llm()

    response = await router_llm.ainvoke([
        SystemMessage(content='Classify if the query needs document retrieval. Respond with JSON: {"needs_retrieval": true/false}'),
        HumanMessage(content=query),
    ])

    try:
        result = json.loads(response.content)
        route = "retrieve" if result.get("needs_retrieval", False) else "direct"
    except (json.JSONDecodeError, AttributeError):
        route = "retrieve"

    return {"route": route}


async def retrieve_node(state: RAGState) -> dict:
    """Retrieve relevant documents from vector store with deduplication."""
    last_message = state["messages"][-1]
    query = last_message.content if hasattr(last_message, "content") else str(last_message)

    vectorstore = _get_vectorstore(state.get("collection_name", "default"))
    docs = await vectorstore.asimilarity_search(query, k=settings.top_k * 2)

    if not docs:
        return {"context": "", "route": "retrieve"}

    seen = set()
    unique_docs = []
    for doc in docs:
        source = doc.metadata.get("source", "Unknown")
        chunk_idx = doc.metadata.get("chunk_index", "N/A")
        key = (source, chunk_idx)
        if key not in seen:
            seen.add(key)
            unique_docs.append(doc)
            if len(unique_docs) >= settings.top_k:
                break

    context_parts = []
    for i, doc in enumerate(unique_docs, 1):
        source = doc.metadata.get("source", "Unknown")
        chunk_idx = doc.metadata.get("chunk_index", "N/A")
        context_parts.append(f"[Source {i}: {source}, chunk {chunk_idx}]\n{doc.page_content}")

    context = "\n\n" + "=" * 60 + "\n\n".join(context_parts)
    return {"context": context, "route": "retrieve", "retrieved_docs": unique_docs}


async def generate_node(state: RAGState) -> dict:
    """Generate answer with streaming support."""
    last_message = state["messages"][-1]
    query = last_message.content if hasattr(last_message, "content") else str(last_message)

    llm = _get_llm()

    if state["route"] == "retrieve" and state.get("context"):
        system_prompt = """You are a research assistant. Answer based ONLY on the provided context. If the context doesn't contain enough information, say "I don't know". Do not invent information."""
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Context:\n{state['context']}\n\nQuestion: {query}"),
        ]
    else:
        today = datetime.now().strftime("%B %d, %Y")
        system_prompt = f"""You are a helpful assistant. Answer the user's question directly and concisely. Today's date is {today}."""
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=query),
        ]

    full_response = ""
    async for chunk in llm.astream(messages):
        full_response += chunk.content

    return {"messages": [AIMessage(content=full_response)]}


def route_decision(state: RAGState) -> Literal["retrieve", "generate"]:
    """Route to retrieve or generate based on classification."""
    return "retrieve" if state["route"] == "retrieve" else "generate"


def build_graph():
    """Build and compile the RAG graph with checkpointer."""
    graph = (
        StateGraph(RAGState)
        .add_node("router", route_node)
        .add_node("retrieve", retrieve_node)
        .add_node("generate", generate_node)
        .add_edge(START, "router")
        .add_conditional_edges("router", route_decision, ["retrieve", "generate"])
        .add_edge("retrieve", "generate")
        .add_edge("generate", END)
    )

    return graph


async def get_checkpointer() -> AsyncSqliteSaver:
    """Create and return an async SQLite checkpointer."""
    db_path = Path(settings.sqlite_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = await aiosqlite.connect(str(db_path))
    checkpointer = AsyncSqliteSaver(conn)
    await checkpointer.setup()
    return checkpointer


async def stream_query(
    query: str,
    collection_name: str,
    thread_id: str | None = None,
    retrieval_settings=None,
) -> AsyncGenerator[tuple[str, str | list[dict]], None]:
    """Stream RAG response with conversation memory."""
    if thread_id is None:
        thread_id = str(uuid.uuid4())

    graph = build_graph()
    checkpointer = await get_checkpointer()

    try:
        rag_pipeline = graph.compile(checkpointer=checkpointer)

        config = {"configurable": {"thread_id": thread_id}}
        initial_state = {
            "messages": [HumanMessage(content=query)],
            "route": "",
            "context": "",
            "collection_name": collection_name,
        }

        sources_yielded = False

        async for event in rag_pipeline.astream_events(
            initial_state,
            config=config,
            version="v2",
        ):
            if event["event"] == "on_chat_model_stream":
                metadata = event.get("metadata", {})
                if metadata.get("langgraph_node") == "generate":
                    chunk = event["data"].get("chunk")
                    if chunk and chunk.content:
                        if not sources_yielded:
                            yield ("sources", [])
                            sources_yielded = True
                        yield ("token", chunk.content)

            elif event["event"] == "on_chain_end":
                metadata = event.get("metadata", {})
                if metadata.get("langgraph_node") == "retrieve":
                    output = event.get("data", {}).get("output", {})
                    retrieved_docs = output.get("retrieved_docs", [])
                    if retrieved_docs and not sources_yielded:
                        sources = [
                            {
                                "chunk_id": str(doc.metadata.get("chunk_index", i)),
                                "content_preview": doc.page_content[:200],
                                "source": doc.metadata.get("source"),
                            }
                            for i, doc in enumerate(retrieved_docs)
                        ]
                        yield ("sources", sources)
                        sources_yielded = True

        if not sources_yielded:
            yield ("sources", [])

        yield ("done", None)

    finally:
        await checkpointer.conn.close()
