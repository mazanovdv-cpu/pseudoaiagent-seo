"""Клиент LLM через API, совместимый с OpenAI.

Модуль не зависит от остального приложения: ему нужны только пакет ``openai``
и параметры доступа. Их можно передать явно или взять из окружения
``PROXYAPI_KEY``, ``PROXYAPI_BASE_URL``, ``PROXYAPI_MODEL``.

Пример::

    import asyncio
    from app.LLM_module import LLMClient, LLMConfig

    async def main() -> None:
        async with LLMClient(LLMConfig.from_env()) as llm:
            text = await llm.complete([
                {"role": "user", "content": "Ответь одним словом: ок"},
            ])
            print(text)

    asyncio.run(main())
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass

from openai import APIConnectionError, APIStatusError, AsyncOpenAI


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    base_url: str
    model: str
    temperature: float = 0.3
    max_tokens: int = 2200
    timeout: float = 120.0

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> LLMConfig:
        env = os.environ if environ is None else environ
        return cls(
            api_key=env.get("PROXYAPI_KEY", ""),
            base_url=env.get("PROXYAPI_BASE_URL", ""),
            model=env.get("PROXYAPI_MODEL", ""),
        )


def missing_settings(config: LLMConfig) -> list[str]:
    missing: list[str] = []
    if not config.api_key.strip():
        missing.append("PROXYAPI_KEY")
    if not config.base_url.strip():
        missing.append("PROXYAPI_BASE_URL")
    if not config.model.strip():
        missing.append("PROXYAPI_MODEL")
    return missing


def ensure_configured(config: LLMConfig) -> None:
    missing = missing_settings(config)
    if not missing:
        return
    names = ", ".join(missing)
    raise ValueError(
        "Не заданы переменные: "
        + names
        + ". Модель указывается в PROXYAPI_MODEL — идентификатор из кабинета ProxyAPI, "
        "который доступен вашему ключу."
    )


class LLMClient:
    """Потоковый и обычный запрос к chat completions."""

    def __init__(self, config: LLMConfig, client: AsyncOpenAI | None = None) -> None:
        self.config = config
        self._owns_client = client is None
        self._client = client or AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url.rstrip("/"),
            timeout=config.timeout,
        )

    async def __aenter__(self) -> LLMClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.close()

    async def stream_chat(self, messages: list[dict]) -> AsyncIterator[str]:
        try:
            stream = await self._client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                stream=True,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )
            async for chunk in stream:
                if not chunk.choices:
                    continue
                yield delta_text(chunk.choices[0].delta)
        except APIStatusError as exc:
            detail = getattr(exc, "message", None) or str(exc)
            raise ValueError(f"Модель вернула ошибку: {detail}") from exc
        except APIConnectionError as exc:
            raise ValueError("Нет соединения с ProxyAPI") from exc

    async def complete(self, messages: list[dict]) -> str:
        parts: list[str] = []
        async for token in self.stream_chat(messages):
            parts.append(token)
        return "".join(parts)


def delta_text(delta: object) -> str:
    content = getattr(delta, "content", None)
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
            else:
                parts.append(str(getattr(item, "text", "") or ""))
        return "".join(parts)
    return str(content)
