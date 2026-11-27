import pytest
from fastapi.testclient import TestClient

from app.database import init_db
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "agents.db"))
    monkeypatch.setenv("PROXYAPI_KEY", "")
    monkeypatch.setenv("PROXYAPI_BASE_URL", "")
    monkeypatch.setenv("PROXYAPI_MODEL", "")
    with TestClient(app) as test_client:
        yield test_client


def test_health_and_interface(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/health").json() == {"status": "ok"}
    page = client.get("/")
    assert page.status_code == 200
    assert "Запустить агента" in page.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_default_agent_and_upsert(client: TestClient) -> None:
    listed = client.get("/api/agents")
    assert listed.status_code == 200
    agents = listed.json()
    assert agents == [{"id": 1, "name": "SEO-Анализ"}]
    detail = client.get("/api/agents/1")
    assert detail.status_code == 200
    assert detail.json()["system_prompt"].startswith("Ты профессиональный SEO-специалист.")
    assert "семантическое ядро" in detail.json()["system_prompt"]

    updated = client.post(
        "/api/agents",
        json={"name": "SEO-Анализ", "system_prompt": "Новый промт для ядра"},
    )
    assert updated.status_code == 200
    assert updated.json()["action"] == "updated"
    assert updated.json()["id"] == 1

    created = client.post(
        "/api/agents",
        json={"name": "Редактор", "system_prompt": "Ты редактор структуры страницы."},
    )
    assert created.status_code == 200
    assert created.json()["action"] == "created"
    names = [item["name"] for item in client.get("/api/agents").json()]
    assert names == ["SEO-Анализ", "Редактор"]

    init_db()
    assert client.get("/api/agents/1").json()["system_prompt"] == "Новый промт для ядра"
    assert client.get("/api/agents/999").status_code == 404
    assert client.delete("/api/agents/999").status_code == 404
    removed = client.delete(f"/api/agents/{created.json()['id']}")
    assert removed.status_code == 204
    assert [item["name"] for item in client.get("/api/agents").json()] == ["SEO-Анализ"]
    assert client.post("/api/agents", json={"name": " ", "system_prompt": "x"}).status_code == 422


def test_analyze_reports_missing_config(client: TestClient) -> None:
    with client.stream(
        "GET",
        "/api/analyze",
        params={"url": "https://example.com", "agent_id": 1},
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())
    assert "PROXYAPI_KEY" in body
    assert "event: done" in body


def test_analyze_blocks_local_url(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROXYAPI_KEY", "test")
    monkeypatch.setenv("PROXYAPI_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("PROXYAPI_MODEL", "configured-model")
    with client.stream(
        "POST",
        "/api/analyze",
        json={"url": "http://127.0.0.1/admin", "agent_name": "SEO-Анализ"},
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())
    assert "локальным" in body
    assert "event: log" in body


def test_analyze_requires_url(client: TestClient) -> None:
    assert client.get("/api/analyze").status_code == 422
    assert client.post("/api/analyze", json={"agent_id": 1}).status_code == 422
