"""Application settings loaded from environment variables."""

import json
import os
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _resolve_project_path(path_value: str) -> str:
    path = Path(path_value)
    if path.is_absolute():
        return str(path)
    return str((PROJECT_ROOT / path).resolve())


def _load_claude_settings() -> dict:
    """Load settings from Claude's settings.json if it exists."""
    claude_settings_path = Path.home() / ".claude" / "settings.json"
    if claude_settings_path.exists():
        try:
            with open(claude_settings_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get("env", {})
        except Exception:
            pass
    return {}


# Load Claude settings and set as environment variables if not already set
_claude_env = _load_claude_settings()
for key, value in _claude_env.items():
    if key not in os.environ:
        os.environ[key] = value

# Force .env values to override stale system environment variables for Anthropic settings
# (pydantic-settings normally lets system env win; we need .env to win for these keys)
try:
    from dotenv import dotenv_values as _dotenv_values
    _env_path = Path(__file__).parent.parent.parent.parent / ".env"
    if _env_path.exists():
        _dotenv = _dotenv_values(_env_path)
        for _key in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"):
            if _key in _dotenv and _dotenv[_key]:
                os.environ[_key] = _dotenv[_key]
except Exception:
    pass


class Settings(BaseSettings):
    # LLM
    anthropic_api_key: str = ""
    anthropic_auth_token: str = ""  # Alternative: sent as Authorization: Bearer (for DashScope proxy)
    anthropic_base_url: Optional[str] = None
    anthropic_model: str = "claude-sonnet-4-20250514"
    openai_api_key: str = ""

    # Database (SQLite for local development, PostgreSQL for production)
    database_url: str = f"sqlite:///{(PROJECT_ROOT / 'data' / 'domain_expert.db').resolve()}"

    # Redis (optional — if unavailable, PDF processing is synchronous)
    redis_url: str = "redis://localhost:6379/0"

    # ChromaDB (embedded mode for local development)
    chroma_host: str = ""  # Empty = use embedded mode
    chroma_port: int = 8001
    vector_db_path: str = str((PROJECT_ROOT / "data" / "chromadb").resolve())

    # File upload
    upload_dir: str = str((PROJECT_ROOT / "data" / "uploads").resolve())
    max_upload_size: int = 104857600  # 100MB
    knowledge_import_concurrency: int = 1

    # Security
    secret_key: str = "change-this-to-a-strong-secret-key"

    # CORS
    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000,http://localhost"
    allowed_origin_regex: str = r"^https?://(localhost|127\.0\.0\.1|0\.0\.0\.0|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3})(:\d+)?$"

    # Proxy settings for external APIs (PubMed, etc.)
    http_proxy: str = ""  # e.g., "http://proxy.company.com:8080"
    https_proxy: str = ""  # e.g., "http://proxy.company.com:8080"

    # Semantic Scholar API (optional — increases rate limit from 1/s to 10/s)
    semantic_scholar_api_key: str = ""
    # Max corpus size for fetching citation network (references + citations_in per paper)
    # Set to 0 to disable network fetching entirely
    semantic_scholar_network_limit: int = 100

    # MinerU PDF-to-Markdown API
    mineru_api_token: str = ""
    mineru_base_url: str = "https://mineru.net"

    # LLM Wiki knowledge base paths
    wiki_dir: str = str((PROJECT_ROOT / "data" / "wiki").resolve())
    wiki_raw_dir: str = str((PROJECT_ROOT / "data" / "wiki" / "raw").resolve())

    model_config = {
        "env_file": "../.env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()

if settings.database_url.startswith("sqlite:///"):
    db_path = settings.database_url.replace("sqlite:///", "", 1)
    settings.database_url = f"sqlite:///{_resolve_project_path(db_path)}"

settings.vector_db_path = _resolve_project_path(settings.vector_db_path)
settings.upload_dir = _resolve_project_path(settings.upload_dir)
settings.wiki_dir = _resolve_project_path(settings.wiki_dir)
settings.wiki_raw_dir = _resolve_project_path(settings.wiki_raw_dir)
