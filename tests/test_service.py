import pytest

from card_assistant.models import NO_DATA, MissingItem, ProductInput, SpecItem, UnsupportedClaim, Verification
from card_assistant.service import CardService, InsufficientDataError

from .conftest import FakeLLM


def test_clean_draft_needs_two_calls(product, make_draft, settings):
    llm = FakeLLM([make_draft()])
    card = CardService(llm, settings).generate(product)
    assert [name for name, _ in llm.prompts] == ["CardDraft", "Verification"]
    assert card.warnings == []
    assert card.meta.attempts == 1 and card.meta.llm_calls == 2


def test_failed_check_triggers_repair_with_feedback(product, make_draft, settings):
    llm = FakeLLM([make_draft(seo_title="М" * 80), make_draft()])
    card = CardService(llm, settings).generate(product)
    assert [name for name, _ in llm.prompts] == ["CardDraft", "CardDraft", "Verification"]
    assert "80 символов" in llm.prompts[1][1]  # исправление получает конкретное замечание
    assert card.meta.attempts == 2 and card.warnings == []


def test_fact_checker_claim_is_repaired(product, make_draft, settings):
    bad = make_draft(seo_description=make_draft().seo_description.replace("Манометр", "Стальной манометр", 1))
    claim = UnsupportedClaim(field="seo_description", quote="Стальной манометр", reason="материал не указан")
    llm = FakeLLM([bad, make_draft()], [Verification(unsupported=[claim])])
    card = CardService(llm, settings).generate(product)
    assert "Стальной манометр" in llm.prompts[2][1]
    assert card.warnings == []


def test_fact_checker_quote_not_in_card_is_ignored(product, make_draft, settings):
    claim = UnsupportedClaim(field="seo_description", quote="фразы нет в карточке", reason="-")
    llm = FakeLLM([make_draft()], [Verification(unsupported=[claim])])
    card = CardService(llm, settings).generate(product)
    assert card.meta.attempts == 1 and card.warnings == []


def test_unfixed_issues_become_warnings(product, make_draft, settings):
    llm = FakeLLM([make_draft(seo_title="М" * 80)] * 3)
    card = CardService(llm, settings).generate(product)
    assert card.meta.attempts == 3
    assert any("80 символов" in w for w in card.warnings)


def test_ungrounded_spec_is_replaced_and_dropped_spec_restored(product, make_draft, settings):
    specs = [
        SpecItem(name="Диапазон измерений", value="0–1,6 МПа", source="диапазон измерений: 0–1,6 МПа"),
        SpecItem(name="Материал корпуса", value="сталь", source="корпус из стали"),
    ]
    llm = FakeLLM([make_draft(specs=specs)] * 3)
    card = CardService(llm, settings).generate(product)
    values = {spec.name: spec.value for spec in card.specs}
    assert values["Материал корпуса"] == NO_DATA
    assert values["Класс точности"] == "1,5"  # модель потеряла — вернули из входа
    assert any("Материал корпуса" in m.name for m in card.missing)


def test_missing_merges_empty_input_fields(make_draft, settings):
    product = ProductInput(name="Манометр показывающий DM 02", specs={"диапазон измерений": "0–1,6 МПа",
                           "класс точности": "1,5", "присоединение": "G1/2", "диаметр корпуса": "100 мм",
                           "материал": ""})
    card = CardService(FakeLLM([make_draft()]), settings).generate(product)
    names = [m.name for m in card.missing]
    assert {"Производитель", "материал", "Степень защиты"} <= set(names)
    assert len(names) == len(set(names))


def test_missing_does_not_duplicate_model_items(product, make_draft, settings):
    specs = [
        *make_draft().specs,
        SpecItem(name="Температура измеряемой среды", value=NO_DATA, source=""),
        SpecItem(name="Температура окружающей среды", value=NO_DATA, source=""),
    ]
    missing = [MissingItem(name="Температура измеряемой и рабочей среды", why="-"),
               MissingItem(name="Степень защиты (IP)", why="-")]
    card = CardService(FakeLLM([make_draft(specs=specs, missing=missing)]), settings).generate(product)
    assert [m.name for m in card.missing] == [
        "Температура измеряемой и рабочей среды", "Степень защиты (IP)", "Температура окружающей среды",
    ]


def test_no_specs_and_no_description_is_rejected(settings):
    llm = FakeLLM([])
    with pytest.raises(InsufficientDataError):
        CardService(llm, settings).generate(ProductInput(name="Манометр", specs={"класс": ""}))
    assert llm.prompts == []  # в модель не ходили
