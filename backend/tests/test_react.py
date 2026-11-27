from app.react import ReactParser


def _feed(parser: ReactParser, parts: list[str]) -> list[dict]:
    events: list[dict] = []
    for part in parts:
        events.extend(parser.feed(part))
    events.extend(parser.finish())
    return events


def test_protocol_split_across_tokens() -> None:
    parser = ReactParser()
    events = _feed(
        parser,
        ["THOU", "GHT: думаю\nACT", "ION: finish\nINPUT:\nFINAL:\nИтог"],
    )
    assert parser.action == "finish"
    assert "думаю" in parser.thought
    assert parser.final == "Итог"
    assert any(event["type"] == "thought_delta" and "думаю" in event["text"] for event in events)
    assert any(event["type"] == "result_delta" and "Итог" in event["text"] for event in events)


def test_fetch_action_and_input() -> None:
    parser = ReactParser()
    _feed(
        parser,
        ["THOUGHT: нужна ещё страница\nACTION: fetch_url\nINPUT: http://1.1.1.1/a\nFINAL:\n"],
    )
    assert parser.action == "fetch_url"
    assert parser.action_input == "http://1.1.1.1/a"
    assert parser.final == ""


def test_short_text_without_protocol_becomes_final() -> None:
    parser = ReactParser()
    _feed(parser, ["Коротко"])
    assert parser.action == ""
    assert parser.final == "Коротко"


def test_long_text_without_protocol_streams_as_final() -> None:
    parser = ReactParser()
    text = "Просто ответ без протокола. " + ("слово " * 30)
    events = _feed(parser, [text])
    assert parser.final.startswith("Просто ответ")
    assert any(event["type"] == "result_delta" for event in events)
