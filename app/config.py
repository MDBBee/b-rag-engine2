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
    router_model: str = "openai/gpt-4o-mini"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    chroma_persist_dir: str = "chroma_db"
    sqlite_db_path: str = "db/checkpoints.db"
    chunk_size: int = 1000
    chunk_overlap: int = 200
    oversized_threshold: int = 2000
    top_k: int = 5
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
