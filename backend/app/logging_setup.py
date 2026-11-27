"""Логи в stdout и, если задан токен, в Better Stack Logtail."""

from __future__ import annotations

import logging

from app.config import get_settings

logger = logging.getLogger("app")
_LOGGERS = ("", "uvicorn", "uvicorn.error", "uvicorn.access")


def configure_logtail() -> None:
    settings = get_settings()
    token = settings.logtail_source_token.strip()
    host = settings.logtail_host.strip()
    if not token or not host:
        logger.info("Logtail выключен")
        return
    if host.startswith("https://"):
        ingest_host = host
    else:
        ingest_host = f"https://{host}"
    try:
        from logtail import LogtailHandler

        handler = LogtailHandler(source_token=token, host=ingest_host)
    except Exception:
        logger.exception("Не удалось подключить Logtail")
        return
    for name in _LOGGERS:
        target = logging.getLogger(name)
        if any(type(item).__name__ == "LogtailHandler" for item in target.handlers):
            continue
        target.addHandler(handler)
        if target.level == logging.NOTSET or target.level > logging.INFO:
            target.setLevel(logging.INFO)
    logger.info("Logtail включён")


def flush_logs() -> None:
    for name in _LOGGERS:
        for handler in logging.getLogger(name).handlers:
            flush = getattr(handler, "flush", None)
            if flush is not None:
                flush()
