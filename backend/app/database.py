"""SQLite, пользователь admin и отдельные агенты каждого пользователя."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import event, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.auth import hash_password, verify_password
from app.config import get_settings
from app.models import Agent, Base, User
from app.prompts import DEFAULT_AGENT_NAME, DEFAULT_SYSTEM_PROMPT

ADMIN_LOGIN = "admin"

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
    _ensure_admin()
    _migrate_legacy_agents()
    _seed_admin_agent()
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


def find_user(db: Session, login: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.login) == login.strip().casefold()))


def copy_agents_from_admin(db: Session, user: User) -> None:
    admin = find_user(db, ADMIN_LOGIN)
    if admin is None or admin.id == user.id:
        return
    agents = db.scalars(select(Agent).where(Agent.user_id == admin.id).order_by(Agent.id))
    for agent in agents:
        db.add(
            Agent(
                user_id=user.id,
                name=agent.name,
                system_prompt=agent.system_prompt,
            )
        )


def _ensure_admin() -> None:
    if SessionLocal is None:
        return
    password = get_settings().admin_password
    if not password:
        logger.warning("ADMIN_PASSWORD не задан, пользователь admin не создан")
        return
    with SessionLocal() as db:
        admin = find_user(db, ADMIN_LOGIN)
        if admin is None:
            salt, digest = hash_password(password)
            db.add(
                User(
                    login=ADMIN_LOGIN,
                    password_salt=salt,
                    password_hash=digest,
                )
            )
            db.commit()
            logger.info("Создан пользователь admin")
            return
        if verify_password(password, admin.password_salt, admin.password_hash):
            return
        salt, digest = hash_password(password)
        admin.password_salt = salt
        admin.password_hash = digest
        db.commit()
        logger.info("Пароль пользователя admin обновлён из окружения")


def _agent_columns() -> set[str]:
    if engine is None:
        return set()
    with engine.connect() as connection:
        return {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(agents)")).fetchall()
        }


def _migrate_legacy_agents() -> None:
    if engine is None or SessionLocal is None:
        return
    columns = _agent_columns()
    if not columns or "user_id" in columns:
        return
    with SessionLocal() as db:
        admin = find_user(db, ADMIN_LOGIN)
        admin_id = None if admin is None else admin.id
    if admin_id is None:
        logger.error("Старые агенты не перенесены: нет пользователя admin")
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE agents_migrated (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name VARCHAR(200) NOT NULL,
                    system_prompt TEXT NOT NULL,
                    UNIQUE (user_id, name),
                    FOREIGN KEY(user_id) REFERENCES users (id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO agents_migrated (id, user_id, name, system_prompt)
                SELECT id, :admin_id, name, system_prompt FROM agents
                """
            ),
            {"admin_id": admin_id},
        )
        connection.execute(text("DROP TABLE agents"))
        connection.execute(text("ALTER TABLE agents_migrated RENAME TO agents"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agents_user_id ON agents (user_id)"))
    logger.info("Существующие агенты закреплены за пользователем admin")


def _seed_admin_agent() -> None:
    if SessionLocal is None:
        return
    with SessionLocal() as db:
        admin = find_user(db, ADMIN_LOGIN)
        if admin is None:
            return
        total = db.scalar(
            select(func.count()).select_from(Agent).where(Agent.user_id == admin.id)
        ) or 0
        if total:
            return
        db.add(
            Agent(
                user_id=admin.id,
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
