"""HTTP API и веб-форма. Запуск: python -m card_assistant serve."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from . import render
from .config import PROJECT_ROOT, Settings
from .llm import AnthropicClient, LLMError
from .models import CardResponse, ProductInput
from .service import CardService, InsufficientDataError

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
EXAMPLE_DIRS = (PROJECT_ROOT / "examples" / "input", PROJECT_ROOT / "examples" / "edge_cases")

_ERROR_TEXT = {
    "missing": "обязательное поле",
    "string_too_short": "не может быть пустым",
    "string_type": "ожидается строка",
    "dict_type": "ожидается объект вида {\"название\": \"значение\"}",
    "model_attributes_type": "ожидается JSON-объект с полями name, manufacturer, specs, description",
}


def _describe_error(error: dict[str, Any]) -> str:
    kind = error.get("type", "")
    ctx = error.get("ctx") or {}
    if kind == "json_invalid":
        return f"некорректный JSON: {ctx.get('error', error.get('msg'))}"
    location = ".".join(str(part) for part in error.get("loc", ()) if part != "body") or "запрос"
    if kind == "string_too_long":
        text = f"слишком длинное значение, максимум {ctx.get('max_length')} символов"
    elif kind == "value_error":
        text = str(ctx.get("error", error.get("msg")))
    else:
        text = _ERROR_TEXT.get(kind, error.get("msg", "некорректное значение"))
    return f"{location}: {text}"


@lru_cache
def get_service() -> CardService:
    settings = Settings.from_env()
    return CardService(AnthropicClient(settings), settings)


def create_app() -> FastAPI:
    app = FastAPI(
        title="AI-помощник для карточек КИП",
        description="Черновик карточки товара для B2B-магазина по данным о приборе.",
        version="1.0.0",
    )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [_describe_error(error) for error in exc.errors()]
        return JSONResponse(status_code=422, content={"error": "Некорректные входные данные", "details": details})

    @app.exception_handler(InsufficientDataError)
    async def _insufficient(_: Request, exc: InsufficientDataError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": str(exc), "missing": exc.missing})

    @app.exception_handler(LLMError)
    async def _llm_error(_: Request, exc: LLMError) -> JSONResponse:
        log.warning("LLM: %s", exc.message)
        return JSONResponse(status_code=exc.status_code, content={"error": exc.message})

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        settings = Settings.from_env()
        return {"status": "ok", "model": settings.model, "api_key_configured": settings.api_key_configured}

    @app.get("/api/examples")
    def examples() -> list[dict[str, Any]]:
        """Примеры из examples/input и examples/edge_cases — для кнопок «Пример» в форме."""
        return [
            {"id": path.stem, "data": json.loads(path.read_text(encoding="utf-8"))}
            for directory in EXAMPLE_DIRS
            for path in sorted(directory.glob("*.json"))
        ]

    @app.post("/api/cards", response_model=CardResponse)
    def create_card(product: ProductInput, service: CardService = Depends(get_service)) -> CardResponse:
        card = service.generate(product)
        return CardResponse(card=card, markdown=render.to_markdown(card), text=render.to_text(card))

    return app


app = create_app()
