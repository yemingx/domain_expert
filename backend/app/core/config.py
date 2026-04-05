"""Application settings loaded from environment variables."""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # LLM
    anthropic_api_key: str = ""
    anthropic_auth_token: str = ""  # Alternative: sent as Authorization: Bearer (for DashScope proxy)
    anthropic_base_url: Optional[str] = None
    anthropic_model: str = "claude-sonnet-4-20250514"
    openai_api_key: str = ""

    # Database (SQLite for local development, PostgreSQL for production)
    database_url: str = "sqlite:///./data/domain_expert.db"

    # Redis (optional — if unavailable, PDF processing is synchronous)
    redis_url: str = "redis://localhost:6379/0"

    # ChromaDB (embedded mode for local development)
    chroma_host: str = ""  # Empty = use embedded mode
    chroma_port: int = 8001
    vector_db_path: str = "./data/chromadb"

    # File upload
    upload_dir: str = "./data/uploads"
    max_upload_size: int = 104857600  # 100MB

    # Security
    secret_key: str = "change-this-to-a-strong-secret-key"

    # CORS
    allowed_origins: str = "http://localhost:5173,http://localhost:3000,http://localhost"

    # Proxy settings for external APIs (PubMed, etc.)
    http_proxy: str = ""  # e.g., "http://proxy.company.com:8080"
    https_proxy: str = ""  # e.g., "http://proxy.company.com:8080"

    model_config = {
        "env_file": "../.env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
