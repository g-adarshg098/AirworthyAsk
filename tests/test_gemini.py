import json

import httpx
import pytest

from app.config import Settings
from app.gemini import GeminiError, _raise_http_error, generate, stream


def response(status_code, data=None):
    class FakeResponse:
        def __init__(self):
            self.status_code = status_code

        def json(self):
            return data

    return FakeResponse()


def test_provider_error_includes_message_and_does_not_retry_unknown_model():
    with pytest.raises(GeminiError, match="HTTP 404: model was not found") as error:
        _raise_http_error(response(404, {"error": {"message": "model was not found"}}))

    assert not error.value.retryable


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.urls = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def post(self, url, **_):
        self.urls.append(url)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response

    def stream(self, method, url, **_):
        self.urls.append(url)
        return next(self.responses)


class FakeStreamingResponse:
    def __init__(self, status_code, lines=()):
        self.status_code = status_code
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def iter_lines(self):
        return iter(self.lines)


def structured_response(answer):
    return response(
        200,
        {
            "candidates": [{"content": {"parts": [{"text": json.dumps({"answer": answer})}]}}],
            "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 4},
        },
    )


def test_generate_retries_then_uses_fallback_model(monkeypatch):
    client = FakeClient([response(503), response(503), structured_response("ready")])
    monkeypatch.setattr("app.gemini.httpx.Client", lambda **_: client)
    monkeypatch.setattr("app.gemini.time.sleep", lambda _: None)
    settings = Settings(
        gemini_api_key="test-key",
        gemini_model="primary",
        gemini_fallback_model="fallback",
        gemini_retries=1,
    )

    result = generate("test", settings)

    assert result.answer == "ready"
    assert result.model == "fallback"
    assert len(client.urls) == 3
    assert client.urls[0].endswith("/models/primary:generateContent")
    assert client.urls[-1].endswith("/models/fallback:generateContent")


def test_generate_retries_timeout(monkeypatch):
    client = FakeClient([httpx.ReadTimeout("timed out"), structured_response("ready")])
    monkeypatch.setattr("app.gemini.httpx.Client", lambda **_: client)
    monkeypatch.setattr("app.gemini.time.sleep", lambda _: None)
    settings = Settings(
        gemini_api_key="test-key",
        gemini_model="primary",
        gemini_fallback_model="fallback",
        gemini_retries=1,
    )

    result = generate("test", settings)

    assert result.answer == "ready"
    assert result.model == "primary"
    assert len(client.urls) == 2


def test_stream_retries_primary_then_streams_fallback(monkeypatch):
    stream_payload = {
        "candidates": [{"content": {"parts": [{"text": '{"answer":"ready"}'}]}}],
        "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 4},
    }
    client = FakeClient(
        [
            FakeStreamingResponse(503),
            FakeStreamingResponse(200, [f"data: {json.dumps(stream_payload)}"]),
        ]
    )
    monkeypatch.setattr("app.gemini.httpx.Client", lambda **_: client)
    monkeypatch.setattr("app.gemini.time.sleep", lambda _: None)
    settings = Settings(
        gemini_api_key="test-key",
        gemini_model="primary",
        gemini_fallback_model="fallback",
        gemini_retries=0,
    )

    events = list(stream("test", settings))

    assert events[0] == ("delta", '{"answer":"ready"}')
    assert events[1][0] == "complete"
    assert events[1][1].model == "fallback"
    assert client.urls[0].endswith("/models/primary:streamGenerateContent")
    assert client.urls[1].endswith("/models/fallback:streamGenerateContent")


def test_generate_reports_missing_api_key():
    with pytest.raises(GeminiError, match="GEMINI_API_KEY is not configured"):
        generate("test", Settings(gemini_api_key=None))
