import pytest
from fastapi.testclient import TestClient

from app.database import init_db
from app.main import app


ADMIN_PASSWORD = "test-admin"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "agents.db"))
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PASSWORD)
    monkeypatch.setenv("PROXYAPI_KEY", "")
    monkeypatch.setenv("PROXYAPI_BASE_URL", "")
    monkeypatch.setenv("PROXYAPI_MODEL", "")
    with TestClient(app) as test_client:
        yield test_client


def login_admin(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"login": "admin", "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    assert response.json()["login"] == "admin"


def test_health_and_interface(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/health").json() == {"status": "ok"}
    page = client.get("/")
    assert page.status_code == 200
    assert "Запустить агента" in page.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_default_agent_and_upsert(client: TestClient) -> None:
    assert client.get("/api/agents").status_code == 401
    login_admin(client)
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
    login_admin(client)
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
    login_admin(client)
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


def test_register_copies_admin_agents(client: TestClient) -> None:
    login_admin(client)
    created = client.post(
        "/api/agents",
        json={"name": "Редактор", "system_prompt": "Промт администратора."},
    )
    assert created.status_code == 200
    assert client.post("/api/auth/logout").status_code == 204

    unknown = client.post("/api/auth/login", json={"login": "student", "password": "1"})
    assert unknown.status_code == 404
    duplicate_admin = client.post(
        "/api/auth/register",
        json={"login": "Admin", "password": "other"},
    )
    assert duplicate_admin.status_code == 409

    registered = client.post(
        "/api/auth/register",
        json={"login": "student", "password": "1"},
    )
    assert registered.status_code == 200
    assert registered.json()["login"] == "student"
    student_names = [item["name"] for item in client.get("/api/agents").json()]
    assert student_names == ["SEO-Анализ", "Редактор"]
    student_editor = client.get("/api/agents").json()[1]
    assert client.get(f"/api/agents/{student_editor['id']}").json()["system_prompt"] == "Промт администратора."

    changed = client.post(
        "/api/agents",
        json={"name": "Редактор", "system_prompt": "Свой промт студента."},
    )
    assert changed.json()["action"] == "updated"
    assert client.post("/api/auth/logout").status_code == 204
    login_admin(client)
    admin_editor = next(item for item in client.get("/api/agents").json() if item["name"] == "Редактор")
    assert client.get(f"/api/agents/{admin_editor['id']}").json()["system_prompt"] == "Промт администратора."
    assert client.get(f"/api/agents/{student_editor['id']}").status_code == 404

    wrong = client.post(
        "/api/auth/password",
        json={"current_password": "no", "new_password": "next"},
    )
    assert wrong.status_code == 401
    updated = client.post(
        "/api/auth/password",
        json={"current_password": ADMIN_PASSWORD, "new_password": "next-admin"},
    )
    assert updated.status_code == 200


def test_legacy_agents_belong_to_admin(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sqlite3

    database = tmp_path / "legacy.db"
    monkeypatch.setenv("DATABASE_PATH", str(database))
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PASSWORD)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE agents (id INTEGER PRIMARY KEY, name VARCHAR(200) UNIQUE NOT NULL, system_prompt TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO agents (name, system_prompt) VALUES ('Старый', 'промт из прежней базы')"
        )
    init_db()
    with TestClient(app) as test_client:
        login_admin(test_client)
        agents = test_client.get("/api/agents").json()
        assert [item["name"] for item in agents] == ["Старый"]
        detail = test_client.get(f"/api/agents/{agents[0]['id']}")
        assert "прежней базы" in detail.json()["system_prompt"]


def test_analyze_requires_url(client: TestClient) -> None:
    login_admin(client)
    assert client.get("/api/analyze").status_code == 422
    assert client.post("/api/analyze", json={"agent_id": 1}).status_code == 422
