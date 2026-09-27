import json
from datetime import datetime
from typing import Annotated, AsyncGenerator, TypedDict, Literal

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage

from app.config import settings
from app.utils import mongodb


class RAGState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    route: str
    context: str
    collection_name: str
    user_id: str
    project_name: str
    file_name: str
    retrieved_docs: list


async def route_node(state: RAGState) -> dict:
    """Classify query intent: needs document retrieval or direct answer."""
    messages = state["messages"]
    query = messages[-1].content if messages else ""

    response = await mongodb.llm.ainvoke([
        SystemMessage(content="""Determine if the user's question should be answered from their uploaded documents or answered directly.

TRUE (retrieve from documents):
- Questions about document content, findings, methodology, data, recommendations
- Technical questions related to the document's topic
- Questions that reference "the document", "the thesis", "the paper", "the research"
- Questions about specific topics that might be in the documents
- Examples: "What is X?", "How does Y work?", "What are the benefits?", "Were there any recommendations?"

FALSE (answer directly, no retrieval):
- Greetings: "hi", "hello", "hey", "good morning"
- Thanks/gratitude: "thanks", "thank you"
- Questions about the conversation itself: "what is my name?", "what was my last question?", "do you remember?"
- Meta-questions about you: "who are you?", "what can you do?"
- Personal questions: "my name is X", "I am from Y"
- General knowledge unrelated to documents: "what time is it?", "who is the president?", "what's the weather?"

When in doubt, choose TRUE (retrieve).

Respond with JSON: {"needs_retrieval": true/false}"""),
        HumanMessage(content=query),
    ])

    try:
        result = json.loads(response.content)
        needs_retrieval = result.get("needs_retrieval", True)
    except (json.JSONDecodeError, AttributeError):
        needs_retrieval = True

    return {"route": "retrieve" if needs_retrieval else "direct"}


async def retrieve_node(state: RAGState) -> dict:
    """Retrieve relevant documents from vector store with deduplication."""
    messages = state["messages"]
    query = messages[-1].content if messages else ""
    user_id = state.get("user_id", "")
    collection_name = state.get("collection_name", "default")

    pre_filter = {"user_id": user_id, "collection_name": collection_name}
    docs = await mongodb.vectorstore.asimilarity_search(query, k=settings.top_k * 2, pre_filter=pre_filter)

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
    route = state["route"]
    messages = state["messages"]
    project_name = state.get("project_name", "")
    file_name = state.get("file_name", "")
    today = datetime.now().strftime("%B %d, %Y")

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

    full_response = ""
    async for chunk in mongodb.llm.astream(llm_messages):
        full_response += chunk.content

    return {"messages": [AIMessage(content=full_response)]}


def route_decision(state: RAGState) -> Literal["retrieve", "generate"]:
    """Route to retrieve or generate based on classification."""
    return "retrieve" if state["route"] == "retrieve" else "generate"


def build_graph():
    """Build and compile the RAG graph."""
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


async def retrieval_pipeline(
    query: str,
    collection_name: str,
    user_id: str,
    messages: list[dict] = None,
    llm_model: str | None = None,
    project_name: str | None = None,
    file_name: str | None = None,
) -> AsyncGenerator[tuple[str, str | list[dict]], None]:
    """Stream RAG response with conversation history from frontend."""
    history = convert_messages(messages or [])
    all_messages = history + [HumanMessage(content=query)]

    graph = build_graph()
    rag_pipeline = graph.compile()

    input_data = {
        "messages": all_messages,
        "collection_name": collection_name,
        "user_id": user_id,
        "project_name": project_name or "",
        "file_name": file_name or "",
    }

    sources_yielded = False

    async for event in rag_pipeline.astream_events(
        input_data,
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
                            "content_preview": doc.page_content[:300],
                            "source": doc.metadata.get("source"),
                        }
                        for i, doc in enumerate(retrieved_docs)
                    ]
                    yield ("sources", sources)
                    sources_yielded = True

    if not sources_yielded:
        yield ("sources", [])

    yield ("done", None)


def convert_messages(messages: list[dict]) -> list[BaseMessage]:
    """Convert frontend messages to LangChain BaseMessage objects."""
    result = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user":
            result.append(HumanMessage(content=content))
        elif role == "assistant":
            result.append(AIMessage(content=content))
    return result
