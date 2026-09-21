import json
import uuid
from typing import AsyncGenerator, TypedDict, Annotated, Literal
from datetime import datetime

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.mongodb import MongoDBSaver
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, BaseMessage

from app.config import settings
from app.utils import mongodb
from app.utils.mongodb import ensure_conversation_metadata


class RAGState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    route: str
    context: str
    collection_name: str
    user_id: str
    conversational_turns: int

async def route_node(state: RAGState) -> dict:
    """Classify query intent: needs document retrieval or direct answer."""
    conversational_turns = state.get("conversational_turns", 0)
    
    if conversational_turns >= 3:
        return {"route": "redirect", "conversational_turns": conversational_turns}
    
    last_message = state["messages"][-1]
    query = last_message.content if hasattr(last_message, "content") else str(last_message)

    response = await mongodb.llm.ainvoke([
        SystemMessage(content="""Determine if the user's question should be answered from their uploaded documents or answered directly.

TRUE (retrieve from documents) - DEFAULT for most questions:
- Any factual, technical, or topic-specific question
- Questions that COULD be answered by a document (even if not explicitly mentioning "the document")
- Definitions, explanations, methodology, findings, data
- Examples: "What is X?", "How does Y work?", "Explain Z", "What are the benefits of..."

FALSE (answer directly, no retrieval):
- ONLY greetings: "hi", "hello", "hey", "good morning"
- ONLY thanks/gratitude: "thanks", "thank you", "appreciate it"
- ONLY meta-questions about you: "who are you?", "what can you do?", "how do you work?"
- ONLY clearly general knowledge with NO possible document connection: "what time is it?", "who is the president of Finland?", "what's the weather?"

When in doubt, choose TRUE (retrieve). It's better to retrieve and find nothing than to answer from general knowledge.

Respond with JSON: {"needs_retrieval": true/false}"""),
        HumanMessage(content=query),
    ])

    try:
        result = json.loads(response.content)
        needs_retrieval = result.get("needs_retrieval", True)
    except (json.JSONDecodeError, AttributeError):
        needs_retrieval = True

    if needs_retrieval:
        return {"route": "retrieve", "conversational_turns": 0}
    else:
        return {"route": "direct", "conversational_turns": conversational_turns + 1}


async def retrieve_node(state: RAGState) -> dict:
    """Retrieve relevant documents from vector store with deduplication."""
    last_message = state["messages"][-1]
    query = last_message.content if hasattr(last_message, "content") else str(last_message)

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
    conversation_history = state["messages"]
    route = state["route"]
    conversational_turns = state.get("conversational_turns", 0)

    if route == "redirect":
        system_prompt = """You are a research assistant specialized in answering questions about uploaded documents.

The user has asked multiple conversational questions. Politely redirect them to document-related queries.

Example response: "I'm here to help you retrieve information from your uploaded documents. Could you ask me about the content of your documents instead?"

Keep the response brief and friendly."""
        messages = [SystemMessage(content=system_prompt)] + conversation_history
        new_turns = conversational_turns + 1
    elif route == "retrieve" and state.get("context"):
        system_prompt = f"""You are a research assistant specialized in answering questions about uploaded documents.

Answer based ONLY on the provided context. 

IMPORTANT: If the retrieved context is not relevant to answering the question, do NOT answer from your general knowledge. Instead, politely state that the answer cannot be found in the uploaded documents and suggest the user ask about topics covered in their documents.

Context:
{state['context']}"""
        messages = [SystemMessage(content=system_prompt)] + conversation_history
        new_turns = 0
    else:
        today = datetime.now().strftime("%B %d, %Y")
        system_prompt = f"""You are a research assistant specialized in answering questions about uploaded documents.

Your role is to help users understand and extract information from their uploaded documents. If a user asks a question that is outside the scope of document analysis (such as general knowledge questions, opinions, or topics unrelated to their documents), politely explain that you are designed to assist with document-related queries only, and suggest they ask questions about the content of their uploaded documents.

Today's date is {today}."""
        messages = [SystemMessage(content=system_prompt)] + conversation_history
        new_turns = conversational_turns

    full_response = ""
    async for chunk in mongodb.llm.astream(messages):
        full_response += chunk.content

    return {"messages": [AIMessage(content=full_response)], "conversational_turns": new_turns}


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


def get_checkpointer() -> MongoDBSaver:
    """Create and return a MongoDB checkpointer using shared sync client."""
    return MongoDBSaver(mongodb.sync_client, db_name=settings.mongodb_database)


async def retrieval_pipeline(
    query: str,
    collection_name: str,
    user_id: str,
    thread_id: str | None = None,
    retrieval_settings=None,
) -> AsyncGenerator[tuple[str, str | list[dict]], None]:
    """Stream RAG response with conversation memory."""
    if thread_id is None:
        thread_id = str(uuid.uuid4())

    await ensure_conversation_metadata(user_id, collection_name, thread_id)

    graph = build_graph()
    checkpointer = get_checkpointer()

    rag_pipeline = graph.compile(checkpointer=checkpointer)

    config = {"configurable": {"thread_id": thread_id}}
    input_data = {
        "messages": [HumanMessage(content=query)],
        "collection_name": collection_name,
        "user_id": user_id,
    }

    sources_yielded = False

    async for event in rag_pipeline.astream_events(
        input_data,
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
