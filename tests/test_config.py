from app.config import Settings


def test_cors_origins_single():
    settings = Settings(cors_origins="http://localhost:3000", _env_file=None)
    assert settings.cors_origins_list == ["http://localhost:3000"]


def test_cors_origins_multiple():
    settings = Settings(cors_origins="http://localhost:3000,https://example.com", _env_file=None)
    assert settings.cors_origins_list == ["http://localhost:3000", "https://example.com"]


def test_cors_origins_trailing_slash():
    settings = Settings(cors_origins="http://localhost:3000/,https://example.com/", _env_file=None)
    assert settings.cors_origins_list == ["http://localhost:3000", "https://example.com"]


def test_cors_origins_with_spaces():
    settings = Settings(cors_origins="http://localhost:3000 , https://example.com", _env_file=None)
    assert settings.cors_origins_list == ["http://localhost:3000", "https://example.com"]


def test_default_values():
    settings = Settings(_env_file=None)
    assert settings.chunk_size == 1000
    assert settings.chunk_overlap == 200
    assert settings.top_k == 5
    assert settings.max_ingest_file_size == 50 * 1024 * 1024
    assert len(settings.allowed_models) == 7
    assert "openai/gpt-4o-mini" in settings.allowed_models
    assert "qwen/qwen3.7-flash" in settings.allowed_models
    assert "nvidia/nemotron-3.5-super-vl:free" in settings.allowed_models
    assert "minimax/minimax-m3.1-flash:free" in settings.allowed_models
    assert "google/gemma-4-26b-a4b-it:free" in settings.allowed_models
    assert "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free" in settings.allowed_models
    assert "openrouter/free" in settings.allowed_models


def test_env_override(monkeypatch):
    monkeypatch.setenv("CHUNK_SIZE", "2000")
    settings = Settings(_env_file=None)
    assert settings.chunk_size == 2000
