"""HTTP API платформы агентов и раздача веб-интерфейса."""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import ensure_llm, get_settings
from app.logging_setup import configure_logtail, flush_logs
from app.database import get_db, init_db, session_scope
from app.dynamic_agent import DynamicAgent
from app.models import Agent
from app.report import build_report_pdf
from app.schemas import (
    AgentDetail,
    AgentListItem,
    AgentSaved,
    AgentUpsert,
    AnalyzeRequest,
    ReportRequest,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("app")

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def resolve_frontend() -> Optional[Path]:
    override = os.getenv("FRONTEND_DIR")
    if override:
        path = Path(override)
        return path if (path / "index.html").is_file() else None
    app_dir = Path(__file__).resolve().parent
    for level in (2, 1, 0):
        try:
            candidate = app_dir.parents[level] / "frontend"
        except IndexError:
            continue
        if (candidate / "index.html").is_file():
            return candidate
    return None


FRONTEND_DIR = resolve_frontend()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logtail()
    init_db()
    yield
    flush_logs()


app = FastAPI(
    title="Платформа агентов",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)


class NoCacheStatic(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def to_sse(event: dict) -> str:
    if event["type"] == "result_delta":
        return sse("result", {"delta": event.get("text", "")})
    if event["type"] == "result_full":
        return sse("result", {"full": event.get("text", "")})
    return sse("log", event)


def load_agent(agent_id: int | None, agent_name: str | None) -> tuple[str, str]:
    if agent_id is None and not (agent_name and agent_name.strip()):
        raise ValueError("Укажите агента")
    with session_scope() as db:
        agent = None
        if agent_id is not None:
            agent = db.get(Agent, agent_id)
        else:
            agent = db.scalar(select(Agent).where(Agent.name == agent_name.strip()))
        if agent is None:
            raise ValueError("Агент не найден")
        return agent.name, agent.system_prompt


async def analyze_events(
    request: Request,
    url: str,
    agent_id: int | None,
    agent_name: str | None,
):
    yield ": connected\n\n"
    try:
        name, prompt = load_agent(agent_id, agent_name)
        settings = get_settings()
        ensure_llm(settings)
        agent = DynamicAgent(
            system_prompt=prompt,
            agent_name=name,
            url=url,
            settings=settings,
        )

        async def should_stop() -> bool:
            return await request.is_disconnected()

        async for event in agent.run(should_stop=should_stop):
            if await request.is_disconnected():
                break
            yield to_sse(event)
        yield sse("done", {})
    except ValueError as exc:
        yield sse("log", {"type": "error", "text": str(exc)})
        yield sse("done", {})
    except Exception:
        logger.exception("Сбой анализа")
        yield sse("log", {"type": "error", "text": "Не удалось выполнить анализ"})
        yield sse("done", {})


@app.get("/health")
@app.get("/api/health")
def health() -> dict:
    logger.info("health status=ok")
    return {"status": "ok"}


@app.get("/api/agents", response_model=list[AgentListItem])
def list_agents(db: Session = Depends(get_db)) -> list[Agent]:
    return list(db.scalars(select(Agent).order_by(Agent.id)))


@app.get("/api/agents/{agent_id}", response_model=AgentDetail)
def get_agent(agent_id: int, db: Session = Depends(get_db)) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Агент не найден")
    return agent


@app.post("/api/agents", response_model=AgentSaved)
def save_agent(payload: AgentUpsert, db: Session = Depends(get_db)) -> dict:
    existing = db.scalar(select(Agent).where(Agent.name == payload.name))
    if existing is None:
        existing = Agent(name=payload.name, system_prompt=payload.system_prompt)
        db.add(existing)
        action = "created"
    else:
        existing.system_prompt = payload.system_prompt
        action = "updated"
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Агент с таким именем уже сохраняется") from exc
    db.refresh(existing)
    return {
        "id": existing.id,
        "name": existing.name,
        "system_prompt": existing.system_prompt,
        "action": action,
    }


@app.delete("/api/agents/{agent_id}", status_code=204)
def delete_agent(agent_id: int, db: Session = Depends(get_db)) -> Response:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Агент не найден")
    db.delete(agent)
    db.commit()
    return Response(status_code=204)


@app.get("/api/analyze")
async def analyze_get(
    request: Request,
    url: str,
    agent_id: Optional[int] = None,
    agent_name: Optional[str] = None,
) -> StreamingResponse:
    return StreamingResponse(
        analyze_events(request, url.strip(), agent_id, agent_name),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@app.post("/api/analyze")
async def analyze_post(request: Request, payload: AnalyzeRequest) -> StreamingResponse:
    return StreamingResponse(
        analyze_events(request, payload.url, payload.agent_id, payload.agent_name),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@app.post("/api/report")
def download_report(payload: ReportRequest) -> Response:
    try:
        pdf = build_report_pdf(payload.text, payload.title)
    except Exception as exc:
        logger.exception("Не удалось собрать PDF")
        raise HTTPException(status_code=500, detail="Не удалось собрать PDF") from exc
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": "attachment; filename=\"otchet.pdf\"; filename*=UTF-8''%D0%9E%D1%82%D1%87%D0%B5%D1%82.pdf"
        },
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


if FRONTEND_DIR is not None:
    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(
            FRONTEND_DIR / "index.html",
            headers={"Cache-Control": "no-cache"},
        )

    app.mount("/static", NoCacheStatic(directory=str(FRONTEND_DIR)), name="static")
