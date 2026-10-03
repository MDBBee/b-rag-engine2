from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent.parent / ".env",
        extra="ignore",
    )

    openrouter_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    llm_model: str = "openai/gpt-4o-mini"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    mongodb_uri: str = ""
    mongodb_database: str = "b-rag"
    chunk_size: int = 1000
    chunk_overlap: int = 200
    oversized_threshold: int = 2000
    top_k: int = 5
    cors_origins: str = "http://localhost:3000"
    auth_secret: str = ""
    max_ingest_file_size: int = 50 * 1024 * 1024
    max_processing_file_size: int = 100 * 1024 * 1024

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
