from functools import lru_cache
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "CyberSec Career Intelligence API"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    database_url: str | None = None
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "cybersec"
    db_user: str = "cybersec"
    db_password: str = ""
    redis_url: str = "redis://localhost:6379/0"
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "llama3.2:latest"
    openwebui_base_url: str | None = None
    openwebui_api_key: str | None = None
    openwebui_timeout_seconds: float | None = None
    ai_provider: str = "ollama"
    ai_model: str | None = None
    ollama_timeout_seconds: float = 90.0
    ollama_retries: int = 2
    admin_api_key: str | None = None
    max_request_bytes: int = 1_048_576
    max_research_bytes: int = 500_000
    url_import_timeout_seconds: float = 10.0
    url_import_max_bytes: int = 1_000_000
    url_import_max_redirects: int = 5
    research_request_timeout_seconds: float = 15.0
    research_response_max_bytes: int = 1_000_000
    research_retry_count: int = 2
    research_retry_base_seconds: float = 1.0
    research_max_items_per_run: int = 50
    research_scheduler_enabled: bool = True
    research_scheduler_poll_seconds: int = 30
    research_lock_ttl_seconds: int = 900
    research_allowed_user_agent: str = "CyberSecCareerIntelligenceResearch/1.0"
    research_default_respect_robots: bool = True
    linkedin_authorized_api_base_url: str | None = None
    linkedin_authorized_api_key: str | None = None
    licensed_job_provider_base_url: str | None = None
    licensed_job_provider_api_key: str | None = None
    employer_ats_api_base_url: str | None = None
    employer_ats_api_key: str | None = None
    job_search_retention_days: int = 90

    cors_origins: str = "http://localhost:3100,http://127.0.0.1:3100"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        password = f":{quote_plus(self.db_password)}" if self.db_password else ""
        return f"postgresql+psycopg://{self.db_user}{password}@{self.db_host}:{self.db_port}/{self.db_name}"

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
