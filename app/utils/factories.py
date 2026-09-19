from langchain_chroma import Chroma
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.config import settings


def get_embeddings() -> OpenAIEmbeddings:
    """Create OpenAI embeddings client configured with OpenRouter."""
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        openai_api_key=settings.openrouter_api_key,
        openai_api_base=settings.openrouter_base_url,
    )


def get_llm() -> ChatOpenAI:
    """Create ChatOpenAI client for answer generation."""
    return ChatOpenAI(
        model=settings.llm_model,
        openai_api_key=settings.openrouter_api_key,
        openai_api_base=settings.openrouter_base_url,
        temperature=0,
    )


def get_router_llm() -> ChatOpenAI:
    """Create ChatOpenAI client for intent routing."""
    return ChatOpenAI(
        model=settings.router_model,
        openai_api_key=settings.openrouter_api_key,
        openai_api_base=settings.openrouter_base_url,
        temperature=0,
    )


def get_vectorstore(collection_name: str) -> Chroma:
    """Create ChromaDB vector store for a given collection."""
    return Chroma(
        collection_name=collection_name,
        embedding_function=get_embeddings(),
        persist_directory=settings.chroma_persist_dir,
    )
