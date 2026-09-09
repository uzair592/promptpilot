import os
from functools import lru_cache


class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./promptpilot.db")
    session_cookie_name: str = os.getenv("SESSION_COOKIE_NAME", "promptpilot_session")
    session_ttl_seconds: int = int(os.getenv("SESSION_TTL_SECONDS", "604800"))
    secure_cookies: bool = os.getenv("APP_ENV", "development") == "production"
    cors_origins: list[str] = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
        if origin.strip()
    ]
    llm_provider: str = os.getenv("LLM_PROVIDER", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    llm_model: str = os.getenv("LLM_MODEL", "")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_timeout: float = float(os.getenv("LLM_TIMEOUT", "30"))
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
    storage_path: str = os.getenv("STORAGE_PATH", "./storage")


@lru_cache
def get_settings() -> Settings:
    return Settings()
