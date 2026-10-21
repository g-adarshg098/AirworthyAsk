def test_health_is_fast_and_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "app": "examate-rag", "environment": "test"}
