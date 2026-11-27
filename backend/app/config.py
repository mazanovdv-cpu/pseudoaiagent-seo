"""Настройки из переменных окружения. Секреты в коде не хранятся."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    proxyapi_key: str = ""
    proxyapi_base_url: str = ""
    proxyapi_model: str = ""
    database_path: str = "data/agents.db"
    admin_password: str = ""
    session_secret: str = ""
    logtail_source_token: str = ""
    logtail_host: str = ""


def get_settings() -> Settings:
    return Settings()


def ensure_llm(settings: Settings) -> None:
    from app.LLM_module import LLMConfig, ensure_configured

    ensure_configured(
        LLMConfig(
            api_key=settings.proxyapi_key,
            base_url=settings.proxyapi_base_url,
            model=settings.proxyapi_model,
        )
    )
