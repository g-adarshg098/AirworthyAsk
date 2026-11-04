import json
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class GeminiError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class Generation:
    model: str
    answer: str
    input_tokens: int | None
    output_tokens: int | None


def _url(settings: Settings, model: str, streaming: bool) -> str:
    action = "streamGenerateContent" if streaming else "generateContent"
    return f"{settings.gemini_base_url.rstrip('/')}/models/{quote(model, safe='-')}:{action}"


def _payload(message: str) -> dict:
    return {
        "contents": [{"role": "user", "parts": [{"text": message}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {"answer": {"type": "STRING"}},
                "required": ["answer"],
                "propertyOrdering": ["answer"],
            },
        },
    }


def _tokens(data: dict) -> tuple[int | None, int | None]:
    usage = data.get("usageMetadata", {})
    return usage.get("promptTokenCount"), usage.get("candidatesTokenCount")


def _result(data: dict, model: str) -> Generation:
    try:
        text = "".join(
            part["text"]
            for candidate in data["candidates"]
            for part in candidate["content"]["parts"]
            if "text" in part
        )
        answer = json.loads(text)["answer"]
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("answer must be a non-empty string")
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise GeminiError("Gemini returned an invalid structured response.") from exc

    input_tokens, output_tokens = _tokens(data)
    return Generation(model, answer, input_tokens, output_tokens)


def _raise_http_error(response: httpx.Response) -> None:
    status = response.status_code
    if status >= 400:
        try:
            message = response.json().get("error", {}).get("message")
        except (ValueError, AttributeError):
            message = None
        detail = f": {message[:300]}" if isinstance(message, str) else ""
        raise GeminiError(
            f"Gemini returned HTTP {status}{detail}",
            retryable=status in RETRYABLE_STATUSES,
        )


def _request(
    client: httpx.Client,
    settings: Settings,
    model: str,
    message: str,
) -> Generation:
    try:
        response = client.post(
            _url(settings, model, streaming=False),
            headers={"x-goog-api-key": settings.gemini_api_key or ""},
            json=_payload(message),
        )
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise GeminiError("Gemini request timed out or could not connect.", retryable=True) from exc

    _raise_http_error(response)
    try:
        return _result(response.json(), model)
    except json.JSONDecodeError as exc:
        raise GeminiError("Gemini returned an invalid response.") from exc


def generate(message: str, settings: Settings) -> Generation:
    if not settings.gemini_api_key:
        raise GeminiError("GEMINI_API_KEY is not configured.")

    models = [settings.gemini_model]
    if settings.gemini_fallback_model not in models:
        models.append(settings.gemini_fallback_model)

    last_error = GeminiError("Gemini request failed.")
    with httpx.Client(timeout=settings.gemini_timeout_seconds) as client:
        for model in models:
            for attempt in range(settings.gemini_retries + 1):
                try:
                    return _request(client, settings, model, message)
                except GeminiError as exc:
                    last_error = exc
                    if not exc.retryable:
                        raise
                    logger.warning("Gemini model %s failed; retry %s.", model, attempt + 1)
                    if attempt < settings.gemini_retries:
                        time.sleep(min(0.25 * (2**attempt), 2))
    raise GeminiError(f"Gemini primary and fallback models failed: {last_error}") from last_error


def stream(message: str, settings: Settings) -> Iterator[tuple[str, Generation | str]]:
    if not settings.gemini_api_key:
        raise GeminiError("GEMINI_API_KEY is not configured.")

    models = [settings.gemini_model]
    if settings.gemini_fallback_model not in models:
        models.append(settings.gemini_fallback_model)

    last_error = GeminiError("Gemini request failed.")
    for model in models:
        for attempt in range(settings.gemini_retries + 1):
            emitted = False
            try:
                with httpx.Client(timeout=settings.gemini_timeout_seconds) as client:
                    with client.stream(
                        "POST",
                        _url(settings, model, streaming=True),
                        params={"alt": "sse"},
                        headers={"x-goog-api-key": settings.gemini_api_key},
                        json=_payload(message),
                    ) as response:
                        _raise_http_error(response)
                        input_tokens = output_tokens = None
                        for line in response.iter_lines():
                            if not line.startswith("data:"):
                                continue
                            raw = line.removeprefix("data:").strip()
                            if not raw or raw == "[DONE]":
                                continue
                            try:
                                data = json.loads(raw)
                            except json.JSONDecodeError as exc:
                                raise GeminiError("Gemini returned an invalid stream event.") from exc
                            input_tokens, output_tokens = _tokens(data)
                            text = "".join(
                                part["text"]
                                for candidate in data.get("candidates", [])
                                for part in candidate.get("content", {}).get("parts", [])
                                if "text" in part
                            )
                            if text:
                                emitted = True
                                yield "delta", text
                if not emitted:
                    raise GeminiError("Gemini returned an empty stream.")
                yield "complete", Generation(model, "", input_tokens, output_tokens)
                return
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = GeminiError(
                    "Gemini stream timed out or could not connect.",
                    retryable=not emitted,
                )
                last_error.__cause__ = exc
            except GeminiError as exc:
                last_error = exc

            if emitted or not last_error.retryable:
                raise last_error
            logger.warning("Gemini streaming model %s failed; retry %s.", model, attempt + 1)
            if attempt < settings.gemini_retries:
                time.sleep(min(0.25 * (2**attempt), 2))

    raise GeminiError(f"Gemini primary and fallback models failed: {last_error}") from last_error
