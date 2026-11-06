"""Модели данных: вход сервиса, ответ LLM и итоговая карточка."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

NO_DATA = "данных нет"

MAX_SPECS = 60
MAX_TEXT = 20_000


# --- Вход -----------------------------------------------------------------


class ProductInput(BaseModel):
    """Данные о приборе от контент-менеджера (JSON или веб-форма)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    name: str = Field(min_length=1, max_length=300, description="Название товара")
    manufacturer: str = Field(default="", max_length=200, description="Производитель")
    specs: dict[str, str] = Field(default_factory=dict, description="Характеристики: {название: значение}")
    description: str = Field(default="", max_length=MAX_TEXT, description="Описание или фрагмент паспорта")

    @field_validator("manufacturer", "description", mode="before")
    @classmethod
    def _none_to_empty(cls, value: Any) -> Any:
        return "" if value is None else value

    @field_validator("specs", mode="before")
    @classmethod
    def _normalize_specs(cls, value: Any) -> Any:
        """Числа приводим к строке, null — к пустой строке; ключи чистим от пробелов."""
        if value is None:
            return {}
        if not isinstance(value, dict):
            return value  # pydantic сам вернёт понятную ошибку типа
        if len(value) > MAX_SPECS:
            raise ValueError(f"слишком много характеристик: {len(value)}, максимум {MAX_SPECS}")
        normalized: dict[str, Any] = {}
        for key, raw in value.items():
            key = str(key).strip()
            if not key:
                continue
            if raw is None:
                raw = ""
            elif isinstance(raw, bool):
                raw = "да" if raw else "нет"
            elif isinstance(raw, int | float):
                raw = str(raw)
            normalized[key] = raw
        return normalized

    @field_validator("specs")
    @classmethod
    def _strip_values(cls, value: dict[str, str]) -> dict[str, str]:
        return {key: val.strip() for key, val in value.items()}

    @property
    def filled_specs(self) -> dict[str, str]:
        return {key: val for key, val in self.specs.items() if val}

    @property
    def empty_specs(self) -> list[str]:
        return [key for key, val in self.specs.items() if not val]

    def has_enough_data(self) -> bool:
        """Без характеристик и описания текст получится «из воздуха» — такое не генерируем."""
        return bool(self.filled_specs or self.description)

    def empty_fields(self) -> list[str]:
        """Пустые поля входа — их точно нужно уточнить у поставщика."""
        fields = []
        if not self.manufacturer:
            fields.append("Производитель")
        if not self.description:
            fields.append("Описание / фрагмент паспорта")
        fields.extend(self.empty_specs)
        return fields


# --- Ответ LLM (structured output) ------------------------------------------


class SpecItem(BaseModel):
    name: str = Field(description="Название характеристики с заглавной буквы")
    value: str = Field(description=f"Значение из входных данных без изменений или «{NO_DATA}»")
    source: str = Field(
        description=f"Дословная цитата из входных данных, откуда взято значение; пустая строка, если «{NO_DATA}»"
    )


class Commercial(BaseModel):
    audience: list[str] = Field(description="Кому подходит прибор, 2–4 пункта")
    tasks: list[str] = Field(description="Какие задачи решает, 2–4 пункта")
    summary: str = Field(description="1–2 предложения для менеджера: как предложить прибор клиенту")


class MissingItem(BaseModel):
    name: str = Field(description="Что уточнить")
    why: str = Field(description="Почему это важно покупателю")


class CardDraft(BaseModel):
    """Черновик, который возвращает модель. Ограничения длины проверяем в коде, а не схемой."""

    seo_title: str = Field(description="SEO-заголовок, до 70 символов с пробелами")
    seo_description: str = Field(description="SEO-описание, 800–1200 символов с пробелами, без markdown")
    specs: list[SpecItem]
    search_queries: list[str] = Field(description="3–5 поисковых запросов")
    commercial: Commercial
    missing: list[MissingItem]


CardField = Literal["seo_title", "seo_description", "specs", "search_queries", "commercial"]


class UnsupportedClaim(BaseModel):
    field: CardField
    quote: str = Field(description="Точная подстрока из черновика")
    reason: str = Field(description="Почему не подтверждается входными данными")


class Verification(BaseModel):
    unsupported: list[UnsupportedClaim]


# --- Итог -----------------------------------------------------------------


class Issue(BaseModel):
    """Замечание к черновику: из детерминированных проверок или от LLM-фактчекера."""

    code: str
    message: str
    field: str = ""


class CardMeta(BaseModel):
    model: str
    attempts: int
    llm_calls: int
    elapsed_sec: float
    title_length: int
    description_length: int


class ProductCard(BaseModel):
    seo_title: str
    seo_description: str
    specs: list[SpecItem]
    search_queries: list[str]
    commercial: Commercial
    missing: list[MissingItem]
    warnings: list[str] = Field(description="Что не удалось исправить автоматически — проверить вручную")
    meta: CardMeta


class CardResponse(BaseModel):
    card: ProductCard
    markdown: str
    text: str
