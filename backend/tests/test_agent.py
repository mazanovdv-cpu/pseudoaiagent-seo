import asyncio

from app.dynamic_agent import MAX_ITERATIONS, DynamicAgent


def _page(url: str) -> dict:
    return {
        "url": url,
        "title": "Example",
        "h1": ["Заголовок"],
        "description": "Описание",
        "keywords": "",
        "robots": "",
        "canonical": "",
        "og_title": "",
        "og_description": "",
        "headings": ["H2: Раздел"],
        "links": [],
        "text": "Текст страницы про пример.",
    }


def test_agent_finishes_on_first_step() -> None:
    calls = {"n": 0}
    fetched: list[str] = []

    async def completer(_messages):
        calls["n"] += 1
        yield (
            "THOUGHT: данных достаточно\n"
            "ACTION: finish\n"
            "INPUT:\n"
            "FINAL:\n"
            "# Семантическое ядро\n\n- кластер «пример»\n"
        )

    async def fetch(url, client=None):
        fetched.append(url)
        return _page(url)

    async def run():
        agent = DynamicAgent(
            system_prompt="Ты SEO-специалист.",
            agent_name="SEO-Анализ",
            url="https://example.com",
            completer=completer,
            fetch=fetch,
        )
        return [event async for event in agent.run()]

    events = asyncio.run(run())
    assert calls["n"] == 1
    assert fetched == ["https://example.com"]
    assert any(event["type"] == "thought_delta" and "достаточно" in event["text"] for event in events)
    assert any(
        event["type"] == "action" and event["text"] == "Завершаю анализ и формирую итог"
        for event in events
    )
    final = next(event for event in events if event["type"] == "result_full")
    assert "Семантическое ядро" in final["text"]


def test_agent_can_fetch_one_more_page() -> None:
    calls = {"n": 0}

    async def completer(messages):
        calls["n"] += 1
        if calls["n"] == 1:
            yield "THOUGHT: открою связанную страницу\nACTION: fetch_url\nINPUT: http://1.1.1.1/more\nFINAL:\n"
            return
        assert any("OBSERVATION" in message["content"] for message in messages if message["role"] == "user")
        yield "THOUGHT: теперь хватает\nACTION: finish\nINPUT:\nFINAL:\n# Готово\n"

    async def fetch(url, client=None):
        return _page(url)

    async def run():
        agent = DynamicAgent(
            system_prompt="Промт",
            agent_name="Проверка",
            url="http://1.1.1.1/start",
            completer=completer,
            fetch=fetch,
        )
        return [event async for event in agent.run()]

    events = asyncio.run(run())
    assert calls["n"] == 2
    assert any(event["type"] == "action" and "http://1.1.1.1/more" in event["text"] for event in events)
    assert any(event["type"] == "observation" for event in events)
    assert any(event["type"] == "result_full" and "Готово" in event["text"] for event in events)


def test_iteration_limit_is_ten() -> None:
    calls = {"n": 0}

    async def completer(_messages):
        calls["n"] += 1
        yield "THOUGHT: ещё страница\nACTION: fetch_url\nINPUT: http://1.1.1.1/next\nFINAL:\n"

    async def fetch(url, client=None):
        return _page(url)

    async def run():
        agent = DynamicAgent(
            system_prompt="Промт",
            agent_name="Лимит",
            url="http://1.1.1.1/start",
            completer=completer,
            fetch=fetch,
        )
        return [event async for event in agent.run()]

    events = asyncio.run(run())
    assert calls["n"] == MAX_ITERATIONS == 10
    assert any(event["type"] == "result_full" for event in events)
    assert not any(event["type"] == "status" and event["text"] == "Шаг 11 из 10" for event in events)
