import asyncio

import httpx
import pytest

from app.scraper import fetch_page, parse_html, validate_public_url


HTML = """<!doctype html>
<html>
  <head>
    <title>Тестовая страница</title>
    <meta name="description" content="Короткое описание">
    <meta name="keywords" content="тест, ядро">
    <link rel="canonical" href="/canon">
  </head>
  <body>
    <script>secret()</script>
    <style>.x{color:red}</style>
    <h1>Главный заголовок</h1>
    <h2>Раздел</h2>
    <p>Видимый текст</p>
    <a href="/next">Дальше</a>
  </body>
</html>
"""


def test_parse_html_drops_scripts_and_keeps_seo_fields() -> None:
    page = parse_html(HTML.encode(), "https://example.com/page", "text/html")
    assert page["title"] == "Тестовая страница"
    assert page["h1"] == ["Главный заголовок"]
    assert page["description"] == "Короткое описание"
    assert "secret" not in page["text"]
    assert "Видимый текст" in page["text"]
    assert page["headings"] == ["H2: Раздел"]
    assert page["links"][0]["href"] == "https://example.com/next"
    assert page["canonical"] == "https://example.com/canon"


def test_blocks_loopback_and_private_hosts() -> None:
    with pytest.raises(ValueError, match="локальным"):
        validate_public_url("http://127.0.0.1/admin")
    with pytest.raises(ValueError, match="локальным"):
        validate_public_url("http://localhost/admin")
    with pytest.raises(ValueError, match="локальным"):
        validate_public_url("http://169.254.169.254/latest")
    with pytest.raises(ValueError, match="локальным"):
        validate_public_url("http://10.0.0.5/")


def test_rejects_non_http_scheme() -> None:
    with pytest.raises(ValueError):
        validate_public_url("file:///etc/passwd")


def test_redirect_to_loopback_is_blocked() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/secret"})

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
            with pytest.raises(ValueError, match="локальным"):
                await fetch_page("http://1.1.1.1/go", client=client)

    asyncio.run(run())


def test_fetch_parses_html_without_network() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            content=HTML.encode(),
        )

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
            page = await fetch_page("http://1.1.1.1/page", client=client)
        assert page["title"] == "Тестовая страница"
        assert "secret" not in page["text"]

    asyncio.run(run())
