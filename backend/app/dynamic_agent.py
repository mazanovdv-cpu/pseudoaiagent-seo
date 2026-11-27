"""Цикл агента: страница, мысли, действия, итог. Не больше 10 шагов."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Protocol

from app.LLM_module import LLMClient, LLMConfig
from app.config import Settings
from app.prompts import PROTOCOL
from app.react import ReactParser
from app.scraper import PageData, fetch_page, page_to_log, page_to_prompt

logger = logging.getLogger("app.agent")

MAX_ITERATIONS = 10
_FETCH = {"fetch_url", "fetch", "open_url", "get_url"}
_FINISH = {"finish", "final", "done", "stop"}

FetchPage = Callable[..., Awaitable[PageData]]
ShouldStop = Callable[[], Awaitable[bool]]


class Completer(Protocol):
    def __call__(self, messages: list[dict]) -> AsyncIterator[str]: ...


def describe_action(action: str, action_input: str) -> str:
    if action == "fetch_url":
        if action_input:
            return f"Загружаю страницу: {action_input}"
        return "Загружаю страницу: адрес не указан"
    if action == "finish":
        return "Завершаю анализ и формирую итог"
    return f"Неизвестное действие: {action}"


def normalize_action(action: str) -> str:
    token = action.strip().lower()
    if token in _FINISH:
        return "finish"
    if token in _FETCH:
        return "fetch_url"
    return token


class DynamicAgent:
    def __init__(
        self,
        *,
        system_prompt: str,
        agent_name: str,
        url: str,
        settings: Settings | None = None,
        max_iterations: int = MAX_ITERATIONS,
        completer: Completer | None = None,
        fetch: FetchPage = fetch_page,
    ) -> None:
        self.system_prompt = system_prompt
        self.agent_name = agent_name
        self.url = url
        self.settings = settings
        self.max_iterations = max_iterations
        self._completer = completer
        self.fetch = fetch
        self.seen: set[str] = set()

    async def run(self, should_stop: ShouldStop | None = None) -> AsyncIterator[dict]:
        logger.info("Старт анализа, агент=%s, url=%s", self.agent_name, self.url)
        page = await self.fetch(self.url)
        self.seen.add(self.url)
        self.seen.add(page["url"])
        title = page["title"] or "без названия"
        h1 = "; ".join(page["h1"]) or "нет"
        yield {
            "type": "status",
            "text": (
                f"Страница загружена: «{title}». "
                f"Главный заголовок: {h1}. "
                f"Агент «{self.agent_name}», лимит {self.max_iterations} шагов."
            ),
        }
        messages: list[dict] = [
            {
                "role": "system",
                "content": f"{self.system_prompt.rstrip()}\n\n{PROTOCOL}",
            },
            {
                "role": "user",
                "content": (
                    f"Целевой URL: {self.url}\n\n"
                    "Данные страницы, уже собранные бэкендом:\n\n"
                    + page_to_prompt(page)
                ),
            },
        ]
        llm: LLMClient | None = None
        if self._completer is None:
            if self.settings is None:
                raise ValueError("Не переданы настройки модели")
            llm = LLMClient(
                LLMConfig(
                    api_key=self.settings.proxyapi_key,
                    base_url=self.settings.proxyapi_base_url,
                    model=self.settings.proxyapi_model,
                )
            )
        try:
            async for event in self._loop(messages, llm, should_stop):
                yield event
        finally:
            if llm is not None:
                await llm.aclose()

    async def _loop(
        self,
        messages: list[dict],
        llm: LLMClient | None,
        should_stop: ShouldStop | None,
    ) -> AsyncIterator[dict]:
        for step in range(1, self.max_iterations + 1):
            if should_stop is not None and await should_stop():
                return
            yield {"type": "status", "text": f"Шаг {step} из {self.max_iterations}"}
            if step == self.max_iterations:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Лимит шагов исчерпан. Сейчас же верни ACTION: finish "
                            "и полный итог в блоке FINAL. Новые страницы не запрашивай."
                        ),
                    }
                )
            parser = ReactParser()
            logger.info("Шаг %s, агент=%s", step, self.agent_name)
            async for token in self._complete(messages, llm):
                if should_stop is not None and await should_stop():
                    return
                for event in parser.feed(token):
                    yield event
            for event in parser.finish():
                yield event
            messages.append(
                {
                    "role": "assistant",
                    "content": parser.raw.strip() or "(пустой ответ)",
                }
            )
            action = normalize_action(parser.action)
            if not action and (parser.final or parser.raw.strip() or parser.thought):
                action = "finish"
            if action:
                yield {
                    "type": "action",
                    "text": describe_action(action, parser.action_input),
                }
            if action == "fetch_url" and step < self.max_iterations:
                async for event in self._fetch_more(parser.action_input, messages):
                    yield event
                continue
            if action not in {"", "finish"} and step < self.max_iterations:
                note = (
                    "Это действие недоступно. "
                    "Можно загрузить ещё одну страницу или завершить анализ."
                )
                yield {"type": "observation", "text": note}
                messages.append({"role": "user", "content": f"OBSERVATION:\n{note}"})
                continue
            result = parser.final.strip() or parser.thought.strip() or parser.raw.strip()
            if not result:
                result = "Агент не вернул итог."
            yield {"type": "status", "text": "Итог готов"}
            yield {"type": "result_full", "text": result}
            return

    async def _fetch_more(self, target: str, messages: list[dict]) -> AsyncIterator[dict]:
        if not target:
            note = "Адрес страницы не указан. Завершите анализ или укажите полный адрес."
            yield {"type": "observation", "text": note}
            messages.append({"role": "user", "content": f"OBSERVATION:\n{note}"})
            return
        if target in self.seen:
            note = "Эта страница уже загружена. Итог собирается по уже полученным данным."
            yield {"type": "observation", "text": note}
            messages.append({"role": "user", "content": f"OBSERVATION:\n{note}"})
            return
        try:
            extra = await self.fetch(target)
        except ValueError as exc:
            note = f"Не удалось загрузить страницу: {exc}"
            yield {"type": "observation", "text": note}
            messages.append({"role": "user", "content": f"OBSERVATION:\n{note}"})
            return
        self.seen.add(target)
        self.seen.add(extra["url"])
        yield {"type": "observation", "text": page_to_log(extra)}
        messages.append(
            {
                "role": "user",
                "content": "OBSERVATION:\n" + page_to_prompt(extra, text_limit=6000),
            }
        )

    async def _complete(
        self,
        messages: list[dict],
        llm: LLMClient | None,
    ) -> AsyncIterator[str]:
        if self._completer is not None:
            async for token in self._completer(messages):
                if token:
                    yield token
            return
        if llm is None:
            raise ValueError("Не переданы настройки модели")
        async for token in llm.stream_chat(messages):
            yield token
