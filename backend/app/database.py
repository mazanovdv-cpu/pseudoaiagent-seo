"""SQLite и создание дефолтного агента в пустой базе."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.models import Agent, Base
from app.prompts import DEFAULT_AGENT_NAME, DEFAULT_SYSTEM_PROMPT

logger = logging.getLogger("app.database")

engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None


def _database_file() -> Path:
    path = Path(get_settings().database_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def init_db() -> Path:
    global engine, SessionLocal
    path = _database_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    if engine is not None:
        engine.dispose()

    database_url = "sqlite:///" + path.resolve().as_posix()
    engine = _build_engine(database_url)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    _seed_default_agent()
    logger.info("База агентов: %s", path)
    return path


def _build_engine(database_url: str) -> Engine:
    from sqlalchemy import create_engine as sqlalchemy_create_engine

    engine_instance = sqlalchemy_create_engine(
        database_url,
        poolclass=NullPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine_instance, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine_instance


def _seed_default_agent() -> None:
    if SessionLocal is None:
        return
    with SessionLocal() as db:
        total = db.scalar(select(func.count()).select_from(Agent)) or 0
        if total == 0:
            db.add(
                Agent(
                    name=DEFAULT_AGENT_NAME,
                    system_prompt=DEFAULT_SYSTEM_PROMPT,
                )
            )
            db.commit()
            logger.info("Создан дефолтный агент %s", DEFAULT_AGENT_NAME)


@contextmanager
def session_scope() -> Iterator[Session]:
    if SessionLocal is None:
        init_db()
    assert SessionLocal is not None
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db() -> Iterator[Session]:
    if SessionLocal is None:
        init_db()
    assert SessionLocal is not None
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
