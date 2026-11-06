from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import BaseModel

from card_assistant.config import Settings
from card_assistant.models import (
    NO_DATA,
    CardDraft,
    Commercial,
    MissingItem,
    ProductInput,
    SpecItem,
    Verification,
)

DESCRIPTION = (
    "Манометр показывающий DM 02 производства Манотомь предназначен для измерения избыточного давления "
    "в трубопроводах и на технологическом оборудовании. Диапазон измерений — 0–1,6 МПа, класс точности — 1,5. "
)


class FakeLLM:
    """Подставная модель: отдаёт заранее заданные ответы и запоминает, о чём её просили."""

    model = "fake-model"

    def __init__(self, drafts: list[CardDraft], verifications: list[Verification] | None = None) -> None:
        self.drafts = list(drafts)
        self.verifications = list(verifications or [])
        self.prompts: list[tuple[str, str]] = []

    def complete(self, system: str, prompt: str, output_type: type[BaseModel]) -> BaseModel:
        self.prompts.append((output_type.__name__, prompt))
        if output_type is Verification:
            return self.verifications.pop(0) if self.verifications else Verification(unsupported=[])
        return self.drafts.pop(0)


@pytest.fixture
def product() -> ProductInput:
    return ProductInput(
        name="Манометр показывающий DM 02",
        manufacturer="Манотомь",
        specs={"диапазон измерений": "0–1,6 МПа", "класс точности": "1,5", "присоединение": "G1/2",
               "диаметр корпуса": "100 мм"},
        description="Прибор предназначен для измерения избыточного давления...",
    )


@pytest.fixture
def make_draft() -> Callable[..., CardDraft]:
    def factory(**overrides) -> CardDraft:
        description = (DESCRIPTION * 6)[:1000]
        fields = dict(
            seo_title="Манометр DM 02 Манотомь 0–1,6 МПа G1/2",
            seo_description=description,
            specs=[
                SpecItem(name="Диапазон измерений", value="0–1,6 МПа", source="диапазон измерений: 0–1,6 МПа"),
                SpecItem(name="Класс точности", value="1,5", source="класс точности: 1,5"),
                SpecItem(name="Присоединение", value="G1/2", source="присоединение: G1/2"),
                SpecItem(name="Диаметр корпуса", value="100 мм", source="диаметр корпуса: 100 мм"),
                SpecItem(name="Степень защиты", value=NO_DATA, source=""),
            ],
            search_queries=["манометр dm 02", "манометр 1,6 мпа g1/2", "манометр манотомь"],
            commercial=Commercial(
                audience=["Инженеры КИПиА"], tasks=["Контроль избыточного давления"],
                summary="Показывающий манометр на 0–1,6 МПа с резьбой G1/2.",
            ),
            missing=[MissingItem(name="Степень защиты", why="Нужна для выбора места установки")],
        )
        fields.update(overrides)
        return CardDraft(**fields)

    return factory


@pytest.fixture
def settings() -> Settings:
    return Settings(model="fake-model", verify=True, max_repairs=2)
