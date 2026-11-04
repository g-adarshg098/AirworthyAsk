import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app


@pytest.fixture
def client(monkeypatch):
    app.dependency_overrides[get_settings] = lambda: Settings(
        app_name="examate-rag",
        environment="test",
        database_url=None,
        gemini_api_key=None,
    )
    monkeypatch.setattr("app.main.database.initialize_usage_table", lambda database_url: None)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
