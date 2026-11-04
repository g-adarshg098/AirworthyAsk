import json
import logging
from contextlib import asynccontextmanager, closing
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from psycopg2 import Error as DatabaseError

from app import database
from app.config import Settings, get_settings
from app.gemini import GeminiError, Generation, generate, stream
from app.schemas import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    if settings.database_url:
        database.initialize_usage_table(settings.database_url)
    yield


app = FastAPI(title="AirworthyAsk", version="0.2.0", lifespan=lifespan)

SettingsDep = Annotated[Settings, Depends(get_settings)]


def _database_url(settings: Settings) -> str:
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured.")
    return settings.database_url


def _cost(settings: Settings, generation: Generation) -> float | None:
    if generation.model == settings.gemini_model:
        input_rate = settings.gemini_input_cost_per_million
        output_rate = settings.gemini_output_cost_per_million
    elif generation.model == settings.gemini_fallback_model:
        input_rate = settings.gemini_fallback_input_cost_per_million
        output_rate = settings.gemini_fallback_output_cost_per_million
    else:
        return None
    if generation.input_tokens is None or generation.output_tokens is None:
        return None
    if input_rate is None or output_rate is None:
        return None
    return (generation.input_tokens * input_rate + generation.output_tokens * output_rate) / 1_000_000


def _save_usage(settings: Settings, request_id: str, generation: Generation) -> None:
    database.record_usage(
        _database_url(settings),
        request_id,
        generation.model,
        generation.input_tokens,
        generation.output_tokens,
        _cost(settings, generation),
    )


@app.get("/health")
def health(settings: SettingsDep) -> dict:
    """Liveness: the process is up. Must be fast and must not call the LLM or the DB."""
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment}


@app.get("/ready")
def ready(settings: SettingsDep):
    """Readiness: dependencies are reachable. Load balancers and hosts use this."""
    if not settings.database_url:
        return {"status": "ready", "database": "not configured"}
    try:
        with closing(database.connect(settings.database_url)) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
        return {"status": "ready", "database": "ok"}
    except DatabaseError:
        logger.exception("Database readiness check failed.")
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "database": "unavailable"},
        )


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, settings: SettingsDep):
    database_url = _database_url(settings)
    request_id = str(uuid4())

    if not request.stream:
        try:
            generation = generate(request.message, settings)
        except GeminiError as exc:
            logger.warning("Chat generation failed: %s", exc)
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        try:
            database.record_usage(
                database_url,
                request_id,
                generation.model,
                generation.input_tokens,
                generation.output_tokens,
                _cost(settings, generation),
            )
        except DatabaseError as exc:
            logger.exception("Could not save chat usage.")
            raise HTTPException(status_code=503, detail="Usage could not be recorded.") from exc
        return ChatResponse(answer=generation.answer, model=generation.model)

    def events():
        try:
            for event, value in stream(request.message, settings):
                if event == "delta":
                    yield f"data: {json.dumps({'delta': value})}\n\n"
                else:
                    generation = value
                    if not isinstance(generation, Generation):
                        raise RuntimeError("Gemini stream returned invalid completion data.")
                    _save_usage(settings, request_id, generation)
                    yield f"event: done\ndata: {json.dumps({'model': generation.model})}\n\n"
        except GeminiError as exc:
            logger.exception("Streaming chat request failed.")
            yield f'event: error\ndata: {{"detail":{json.dumps(str(exc))}}}\n\n'
        except DatabaseError:
            logger.exception("Could not save streaming chat usage.")
            yield 'event: error\ndata: {"detail":"Usage could not be recorded."}\n\n'

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/usage")
def usage(settings: SettingsDep) -> dict:
    try:
        return database.get_usage(_database_url(settings))
    except HTTPException:
        raise
    except DatabaseError as exc:
        logger.exception("Usage query failed.")
        raise HTTPException(status_code=503, detail="Usage data is unavailable.") from exc
