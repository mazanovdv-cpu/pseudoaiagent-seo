"""Загрузка публичной страницы и очистка HTML для агента."""

from __future__ import annotations

import ipaddress
import socket
from typing import TypedDict
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

MAX_BYTES = 1_500_000
MAX_REDIRECTS = 5
REDIRECT_CODES = {301, 302, 303, 307, 308}
REQUEST_HEADERS = {
    "User-Agent": "AgentPlatform/1.0",
    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9",
}


class PageLink(TypedDict):
    text: str
    href: str


class PageData(TypedDict):
    url: str
    title: str
    h1: list[str]
    description: str
    keywords: str
    robots: str
    canonical: str
    og_title: str
    og_description: str
    headings: list[str]
    links: list[PageLink]
    text: str


def validate_public_url(url: str) -> str:
    raw = url.strip()
    if len(raw) > 2000:
        raise ValueError("Слишком длинный URL")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Нужен абсолютный http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError("URL с логином и паролем не поддерживается")
    host = parsed.hostname.strip("[]").rstrip(".").lower()
    if host in {"localhost"} or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Запросы к локальным и внутренним адресам запрещены, попробуйте отключить VPN")
    for ip in _resolve_ips(host):
        if _is_blocked(ip):
            raise ValueError("Запросы к локальным и внутренним адресам запрещены, попробуйте отключить VPN")
    return raw


def _resolve_ips(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError(f"Не удалось разрешить имя хоста: {host}") from exc
    ips = []
    for item in infos:
        try:
            ips.append(ipaddress.ip_address(item[4][0]))
        except ValueError:
            continue
    if not ips:
        raise ValueError(f"Не удалось разрешить имя хоста: {host}")
    return ips


def _is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


async def fetch_page(url: str, client: httpx.AsyncClient | None = None) -> PageData:
    try:
        if client is not None:
            return await _fetch_with_client(url, client)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0, connect=10.0),
            follow_redirects=False,
            headers=REQUEST_HEADERS,
        ) as owned:
            return await _fetch_with_client(url, owned)
    except ValueError:
        raise
    except httpx.TimeoutException as exc:
        raise ValueError("Сайт не ответил вовремя") from exc
    except httpx.HTTPError as exc:
        raise ValueError("Не удалось подключиться к сайту") from exc


async def _fetch_with_client(url: str, client: httpx.AsyncClient) -> PageData:
    current = url.strip()
    for _ in range(MAX_REDIRECTS):
        current = validate_public_url(current)
        async with client.stream("GET", current, headers=REQUEST_HEADERS) as response:
            status = response.status_code
            location = response.headers.get("location")
            content_type = response.headers.get("content-type", "")
            final_url = str(response.url)
            body = b""
            if status < 400 and status not in REDIRECT_CODES:
                body = await _read_limited(response, MAX_BYTES)
        if status in REDIRECT_CODES:
            if not location:
                raise ValueError("Редирект без адреса")
            current = urljoin(current, location)
            continue
        if status >= 400:
            raise ValueError(f"Страница ответила статусом {status}")
        return parse_html(body, final_url, content_type)
    raise ValueError("Слишком много редиректов")


async def _read_limited(response: httpx.Response, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        if not chunk:
            continue
        remain = limit - total
        if remain <= 0:
            break
        if len(chunk) > remain:
            chunks.append(chunk[:remain])
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)


def parse_html(body: bytes, url: str, content_type: str = "") -> PageData:
    if not _looks_like_html(content_type, body):
        label = content_type.split(";")[0].strip() or "неизвестный тип"
        raise ValueError(f"Ожидался HTML, получен {label}")
    soup = BeautifulSoup(body, "html.parser")
    for tag in soup(["script", "style", "noscript", "template", "svg", "iframe", "canvas"]):
        tag.decompose()

    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    h1 = [tag.get_text(" ", strip=True) for tag in soup.find_all("h1")[:10] if tag.get_text(" ", strip=True)]
    headings: list[str] = []
    for level in (2, 3):
        for tag in soup.find_all(f"h{level}")[:30]:
            text = tag.get_text(" ", strip=True)
            if text:
                headings.append(f"H{level}: {text}")

    raw_text = soup.get_text("\n", strip=True)
    lines = [line.strip() for line in raw_text.splitlines()]
    text = "\n".join(line for line in lines if line)

    return {
        "url": url,
        "title": title,
        "h1": h1,
        "description": _meta(soup, "name", "description"),
        "keywords": _meta(soup, "name", "keywords"),
        "robots": _meta(soup, "name", "robots"),
        "canonical": _canonical(soup, url),
        "og_title": _meta(soup, "property", "og:title"),
        "og_description": _meta(soup, "property", "og:description"),
        "headings": headings,
        "links": _links(soup, url),
        "text": text,
    }


def page_to_prompt(page: PageData, text_limit: int = 12000) -> str:
    headings = "\n".join(f"- {item}" for item in page["headings"][:40]) or "—"
    links = "\n".join(
        f"- {item['text'][:80]} | {item['href']}" for item in page["links"][:25]
    ) or "—"
    text = page["text"][:text_limit]
    if len(page["text"]) > text_limit:
        text += "\n[текст обрезан]"
    return (
        f"URL: {page['url']}\n"
        f"Title: {page['title'] or '—'}\n"
        f"H1: {'; '.join(page['h1']) or '—'}\n"
        f"Meta description: {page['description'] or '—'}\n"
        f"Meta keywords: {page['keywords'] or '—'}\n"
        f"Robots: {page['robots'] or '—'}\n"
        f"Canonical: {page['canonical'] or '—'}\n"
        f"Open Graph title: {page['og_title'] or '—'}\n"
        f"Open Graph description: {page['og_description'] or '—'}\n"
        f"Заголовки:\n{headings}\n"
        f"Ссылки:\n{links}\n"
        f"Текст:\n{text or '—'}"
    )


def page_to_log(page: PageData) -> str:
    h1 = "; ".join(page["h1"]) or "нет"
    title = page["title"] or "без названия"
    return f"Дополнительная страница {page['url']}. Заголовок: {title}. Главный заголовок: {h1}."


def _looks_like_html(content_type: str, body: bytes) -> bool:
    ctype = content_type.lower()
    if any(token in ctype for token in ("html", "xml", "text/")):
        return True
    if ctype and "text" not in ctype and "html" not in ctype and "xml" not in ctype:
        head = body[:300].lstrip().lower()
        return head.startswith(b"<!doctype") or head.startswith(b"<html") or b"<head" in head
    return True


def _meta(soup: BeautifulSoup, attr: str, expected: str) -> str:
    expected_lower = expected.lower()
    for tag in soup.find_all("meta"):
        raw = tag.get(attr)
        if raw and str(raw).lower() == expected_lower:
            return str(tag.get("content") or "").strip()
    return ""


def _canonical(soup: BeautifulSoup, url: str) -> str:
    for link in soup.find_all("link"):
        rel = link.get("rel") or []
        if isinstance(rel, str):
            rel = [rel]
        if any(str(item).lower() == "canonical" for item in rel):
            href = str(link.get("href") or "").strip()
            return urljoin(url, href) if href else ""
    return ""


def _links(soup: BeautifulSoup, url: str) -> list[PageLink]:
    found: list[PageLink] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = urljoin(url, str(anchor["href"]).strip())
        if href in seen:
            continue
        parsed = urlparse(href)
        if parsed.scheme not in {"http", "https"}:
            continue
        seen.add(href)
        text = anchor.get_text(" ", strip=True) or parsed.path or href
        found.append({"text": text, "href": href})
        if len(found) >= 25:
            break
    return found
