from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent.parent / ".env",
        extra="ignore",
    )

    openrouter_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    allowed_embedding_models: list[str] = [
        "text-embedding-3-small",
        "qwen/qwen3-embedding-8b",
    ]
    llm_model: str = "openai/gpt-4o-mini"
    allowed_models: list[str] = [
        "openai/gpt-4o-mini",
        "qwen/qwen3.7-flash",
        "nvidia/nemotron-3.5-super-vl:free",
        "cohere/north-mini-code:free",
        "google/gemma-4-26b-a4b-it:free",
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "openrouter/free",
    ]
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    mongodb_uri: str = ""
    mongodb_database: str = "b-rag"
    chunk_size: int = 1000
    chunk_overlap: int = 200
    text_splitter: str = "recursive"
    oversized_threshold: int = 2000
    top_k: int = 5
    cors_origins: str = "http://localhost:3000"
    auth_secret: str = ""
    max_ingest_file_size: int = 50 * 1024 * 1024
    max_processing_file_size: int = 100 * 1024 * 1024
    rephrase_enabled: bool = True
    max_rephrase_retries: int = 1
    max_context_chunks: int = 200
    ollama_base_url: str = "http://localhost:11434"
    vision_model: str = ""
    ocr_text_threshold: int = 100
    auth_enabled: bool = True
    rate_limit_enabled: bool = True
    tavily_api_key: str = ""
    web_search_enabled: bool = True
    ocr_timeout: int = 300

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()

MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "openai/gpt-4o-mini": 128_000,
    "qwen/qwen3.7-flash": 1_000_000,
    "nvidia/nemotron-3.5-super-vl:free": 1_000_000,
    "cohere/north-mini-code:free": 256_000,
    "google/gemma-4-26b-a4b-it:free": 256_000,
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free": 256_000,
    "openrouter/free": 128_000,
    "text-embedding-3-small": 8_191,
    "qwen/qwen3-embedding-8b": 32_000,
}
