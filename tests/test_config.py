from app.config import Settings


def test_cors_origins_single():
    settings = Settings(cors_origins="http://localhost:3000")
    assert settings.cors_origins_list == ["http://localhost:3000"]


def test_cors_origins_multiple():
    settings = Settings(cors_origins="http://localhost:3000,https://example.com")
    assert settings.cors_origins_list == ["http://localhost:3000", "https://example.com"]


def test_cors_origins_trailing_slash():
    settings = Settings(cors_origins="http://localhost:3000/,https://example.com/")
    assert settings.cors_origins_list == ["http://localhost:3000", "https://example.com"]


def test_cors_origins_with_spaces():
    settings = Settings(cors_origins="http://localhost:3000 , https://example.com")
    assert settings.cors_origins_list == ["http://localhost:3000", "https://example.com"]


def test_default_values():
    settings = Settings()
    assert settings.chunk_size == 1000
    assert settings.chunk_overlap == 200
    assert settings.top_k == 5
    assert settings.max_ingest_file_size == 50 * 1024 * 1024


def test_env_override(monkeypatch):
    monkeypatch.setenv("CHUNK_SIZE", "2000")
    settings = Settings()
    assert settings.chunk_size == 2000
