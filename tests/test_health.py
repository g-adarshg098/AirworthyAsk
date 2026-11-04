def test_health_is_fast_and_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "app": "examate-rag", "environment": "test"}


def test_ready_without_database(client):
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json()["database"] == "not configured"
