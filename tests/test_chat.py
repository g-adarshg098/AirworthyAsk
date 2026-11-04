from app.config import Settings, get_settings
from app.gemini import Generation
from app.main import app


def configured_settings():
    return Settings(
        app_name="examate-rag",
        environment="test",
        database_url="postgresql://app:app@localhost/rag",
        gemini_api_key="test-key",
        gemini_model="gemini-test",
        gemini_input_cost_per_million=0.3,
        gemini_output_cost_per_million=2.5,
    )


def test_chat_returns_structured_answer_and_records_cost(client, monkeypatch):
    settings = configured_settings()
    recorded = []
    monkeypatch.setitem(app.dependency_overrides, get_settings, lambda: settings)
    monkeypatch.setattr(
        "app.main.generate",
        lambda message, configured: Generation("gemini-test", "A regulation.", 100, 50),
    )
    monkeypatch.setattr("app.main.database.record_usage", lambda *args: recorded.append(args))

    response = client.post("/chat", json={"message": "What is a CAR?"})

    assert response.status_code == 200
    assert response.json() == {"answer": "A regulation.", "model": "gemini-test"}
    assert len(recorded) == 1
    assert recorded[0][2:] == ("gemini-test", 100, 50, 0.000155)


def test_chat_streams_json_deltas_and_records_usage(client, monkeypatch):
    settings = configured_settings()
    recorded = []
    monkeypatch.setitem(app.dependency_overrides, get_settings, lambda: settings)
    monkeypatch.setattr(
        "app.main.stream",
        lambda message, configured: iter(
            [
                ("delta", '{"answer":'),
                ("delta", '"A regulation."}'),
                ("complete", Generation("gemini-test", "", 100, 50)),
            ]
        ),
    )
    monkeypatch.setattr("app.main.database.record_usage", lambda *args: recorded.append(args))

    response = client.post("/chat", json={"message": "What is a CAR?", "stream": True})

    assert response.status_code == 200
    assert 'data: {"delta": "{\\"answer\\":"}' in response.text
    assert "event: done" in response.text
    assert len(recorded) == 1


def test_chat_requires_database(client):
    response = client.post("/chat", json={"message": "What is a CAR?"})

    assert response.status_code == 503
    assert response.json()["detail"] == "DATABASE_URL is not configured."


def test_usage_returns_database_summary(client, monkeypatch):
    expected = {
        "total_requests": 1,
        "input_tokens": 100,
        "output_tokens": 50,
        "estimated_cost_usd": 0.000155,
        "recent": [],
    }
    monkeypatch.setitem(app.dependency_overrides, get_settings, lambda: configured_settings())
    monkeypatch.setattr("app.main.database.get_usage", lambda url: expected)

    response = client.get("/usage")

    assert response.status_code == 200
    assert response.json() == expected


def test_chat_rejects_empty_message(client):
    response = client.post("/chat", json={"message": ""})

    assert response.status_code == 422
