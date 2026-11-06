"""Обращение к LLM. Сервис зависит от протокола LLMClient, поэтому в тестах модель подменяется."""

from __future__ import annotations

import logging
import time
from typing import Protocol, TypeVar

import anthropic
import pydantic
from pydantic import BaseModel

from .config import Settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

MAX_TOKENS = 16_000
# Серверный откат на другую модель, если основная откажется отвечать (stop_reason == "refusal").
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(Exception):
    """Ошибка LLM с сообщением для контент-менеджера и HTTP-статусом для API."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class LLMClient(Protocol):
    model: str

    def complete(self, system: str, prompt: str, output_type: type[T]) -> T:
        """Возвращает ответ модели, провалидированный по pydantic-схеме output_type."""
        ...


class AnthropicClient:
    def __init__(self, settings: Settings) -> None:
        self.model = settings.model
        self._effort = settings.effort
        self._fallback = settings.refusal_fallback
        try:
            # Ключ SDK берёт из ANTHROPIC_API_KEY, адрес — из ANTHROPIC_BASE_URL (если нужен прокси).
            self._client = anthropic.Anthropic(timeout=settings.timeout_sec, max_retries=2)
        except anthropic.AnthropicError as exc:
            raise LLMError(f"Клиент Anthropic не создан: {exc}. Проверьте ANTHROPIC_API_KEY в .env.", 503) from exc

    def complete(self, system: str, prompt: str, output_type: type[T]) -> T:
        started = time.monotonic()
        request = dict(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_format=output_type,
            output_config={"effort": self._effort},
        )
        try:
            if self._fallback:
                response = self._client.beta.messages.parse(**request, betas=[FALLBACK_BETA], fallbacks="default")
            else:
                response = self._client.messages.parse(**request)
        except anthropic.AuthenticationError as exc:
            raise LLMError("Anthropic не принял API-ключ. Проверьте ANTHROPIC_API_KEY.", 502) from exc
        except anthropic.PermissionDeniedError as exc:
            raise LLMError(f"У ключа нет доступа к модели {self.model}.", 502) from exc
        except anthropic.NotFoundError as exc:
            raise LLMError(f"Модель {self.model} не найдена. Проверьте CARD_MODEL.", 502) from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("Превышен лимит запросов к Anthropic. Повторите через минуту.", 429) from exc
        except anthropic.BadRequestError as exc:
            raise LLMError(f"Anthropic отклонил запрос: {exc.message}", 502) from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Сервис Anthropic ответил ошибкой {exc.status_code}. Повторите позже.", 502) from exc
        except anthropic.APITimeoutError as exc:
            raise LLMError("Модель не ответила вовремя. Повторите запрос.", 504) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Нет соединения с Anthropic. Проверьте интернет или ANTHROPIC_BASE_URL.", 503) from exc
        except pydantic.ValidationError as exc:
            # Структурированный вывод гарантирует JSON по схеме; сюда попадаем, если ответ обрезан.
            raise LLMError("Модель вернула ответ не по схеме (возможно, обрезан). Повторите запрос.", 502) from exc
        except anthropic.AnthropicError as exc:
            raise LLMError(f"Ошибка клиента Anthropic: {exc}", 502) from exc

        if response.stop_reason == "refusal":
            raise LLMError("Модель отказалась обрабатывать эти данные. Проверьте текст описания.", 422)
        if response.stop_reason == "max_tokens":
            raise LLMError("Ответ модели обрезан по лимиту длины. Сократите описание и повторите.", 502)
        parsed = response.parsed_output
        if parsed is None:
            raise LLMError("Модель вернула пустой ответ. Повторите запрос.", 502)

        log.info(
            "llm %s: %s, %.1f с, токены вход/выход %s/%s, request_id=%s",
            output_type.__name__, response.model, time.monotonic() - started,
            response.usage.input_tokens, response.usage.output_tokens, response._request_id,
        )
        return parsed
