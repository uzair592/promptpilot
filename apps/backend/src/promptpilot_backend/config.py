import os
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str
    session_cookie_name: str
    session_ttl_seconds: int
    secure_cookies: bool
    cors_origins: list[str]
    llm_provider: str
    llm_base_url: str
    llm_model: str
    llm_api_key: str
    llm_timeout: float
    max_upload_bytes: int
    storage_path: str
    url_connect_timeout: float
    url_read_timeout: float
    url_max_response_bytes: int
    url_max_redirects: int

    @classmethod
    def from_environment(cls) -> "Settings":
        app_env = os.getenv("APP_ENV", "development").strip().lower()
        return cls(
            app_env=app_env,
            database_url=normalize_database_url(
                os.getenv("DATABASE_URL", "sqlite:///./promptpilot.db")
            ),
            session_cookie_name=os.getenv("SESSION_COOKIE_NAME", "promptpilot_session"),
            session_ttl_seconds=int(os.getenv("SESSION_TTL_SECONDS", "604800")),
            secure_cookies=app_env == "production",
            cors_origins=[
                origin.strip()
                for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
                if origin.strip()
            ],
            llm_provider=os.getenv("LLM_PROVIDER", "").strip(),
            llm_base_url=os.getenv("LLM_BASE_URL", "").strip(),
            llm_model=os.getenv("LLM_MODEL", "").strip(),
            llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
            llm_timeout=float(os.getenv("LLM_TIMEOUT", "30")),
            max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))),
            storage_path=os.getenv("STORAGE_PATH", "./storage"),
            url_connect_timeout=float(os.getenv("URL_CONNECT_TIMEOUT", "5")),
            url_read_timeout=float(os.getenv("URL_READ_TIMEOUT", "15")),
            url_max_response_bytes=int(
                os.getenv("URL_MAX_RESPONSE_BYTES", str(5 * 1024 * 1024))
            ),
            url_max_redirects=int(os.getenv("URL_MAX_REDIRECTS", "3")),
        )

    def validate(self) -> None:
        if self.app_env not in {"development", "test", "production"}:
            raise ConfigurationError("APP_ENV must be development, test, or production")
        if self.session_ttl_seconds <= 0:
            raise ConfigurationError("SESSION_TTL_SECONDS must be positive")
        if self.llm_timeout <= 0:
            raise ConfigurationError("LLM_TIMEOUT must be positive")
        if self.max_upload_bytes <= 0 or self.url_max_response_bytes <= 0:
            raise ConfigurationError("Upload and URL response limits must be positive")
        if self.url_connect_timeout <= 0 or self.url_read_timeout <= 0:
            raise ConfigurationError("URL timeouts must be positive")
        if self.url_max_redirects < 0:
            raise ConfigurationError("URL_MAX_REDIRECTS must not be negative")

        llm_configuration = (
            self.llm_provider,
            self.llm_base_url,
            self.llm_model,
            self.llm_api_key,
        )
        if any(llm_configuration) and not all(llm_configuration):
            raise ConfigurationError(
                "LLM_PROVIDER, LLM_BASE_URL, LLM_MODEL, and LLM_API_KEY must be set together"
            )

        if self.app_env != "production":
            return
        if self.llm_provider:
            provider_url = urlsplit(self.llm_base_url)
            if (
                provider_url.scheme != "https"
                or not provider_url.hostname
                or provider_url.username is not None
                or provider_url.password is not None
                or provider_url.query
                or provider_url.fragment
            ):
                raise ConfigurationError(
                    "Production LLM_BASE_URL must be an HTTPS URL without credentials"
                )

        database = urlsplit(self.database_url)
        if (
            database.scheme not in {"postgresql+psycopg", "postgresql", "postgres"}
            or not database.hostname
            or not database.path.strip("/")
        ):
            raise ConfigurationError(
                "Production DATABASE_URL must identify a PostgreSQL database"
            )
        if not self.cors_origins or any(
            not _is_https_origin(origin) for origin in self.cors_origins
        ):
            raise ConfigurationError("Production CORS_ORIGINS must contain HTTPS origins only")
        storage_path = Path(self.storage_path)
        if not storage_path.is_absolute():
            raise ConfigurationError("Production STORAGE_PATH must be an absolute path")

    def ensure_storage_directory(self) -> Path:
        storage_path = Path(self.storage_path).resolve()
        storage_path.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.NamedTemporaryFile(dir=storage_path, prefix=".write-check-", delete=True):
                pass
        except OSError as error:
            raise ConfigurationError("STORAGE_PATH must be writable") from error
        return storage_path


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgres://")
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
    return database_url


def _is_https_origin(origin: str) -> bool:
    parsed = urlsplit(origin)
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_environment()
