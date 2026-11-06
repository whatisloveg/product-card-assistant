from card_assistant import checks
from card_assistant.models import NO_DATA, SpecItem


def codes(issues):
    return {issue.code for issue in issues}


def test_numbers_are_canonical():
    assert checks.numbers("0–1,6 МПа, DM 02, G1/2") == {"0", "1.6", "2", "1"}
    assert checks.numbers("1.60") == checks.numbers("1,6")


def test_good_draft_passes(product, make_draft):
    assert checks.run_all(make_draft(), product) == []


def test_length_limits(product, make_draft):
    issues = checks.check_lengths(make_draft(seo_title="М" * 71, seo_description="Коротко.", search_queries=["a"]))
    assert codes(issues) == {"title_length", "description_length", "queries_count"}


def test_unit_conversion_is_caught(product, make_draft):
    draft = make_draft(seo_title="Манометр DM 02 на 16 бар")  # 1,6 МПа пересчитали в бары
    issues = checks.check_numbers(draft, product)
    assert codes(issues) == {"unknown_number"}
    assert "16" in issues[0].message


def test_spec_without_source_is_caught(product, make_draft):
    specs = [SpecItem(name="Степень защиты", value="IP65", source="степень защиты: IP65")]
    issues = checks.check_specs(make_draft(specs=specs), product)
    assert codes(issues) == {"spec_not_grounded"}


def test_quote_from_name_with_or_without_label(product):
    for source in ("name: Манометр показывающий DM 02", "Манометр показывающий DM 02"):
        assert checks.spec_is_grounded(SpecItem(name="Тип", value="показывающий", source=source), product)


def test_spec_value_must_match_quote(product):
    wrong = SpecItem(name="Класс точности", value="1,0", source="класс точности: 1,5")
    assert not checks.spec_is_grounded(wrong, product)
    assert checks.spec_is_grounded(SpecItem(name="Материал", value=NO_DATA, source=""), product)


def test_risky_claims_and_service_text(product, make_draft):
    # «2 года» проверка чисел бы не поймала: двойка есть во входе (DM 02, G1/2) — ловит проверка обещаний.
    description = make_draft().seo_description[:900] + " Гарантия 3 года, доставка по России. Материал не указан."
    issues = checks.run_all(make_draft(seo_description=description), product)
    assert {"risky_claim", "service_text", "unknown_number"} <= codes(issues)


def test_card_contains_ignores_case_and_dashes(make_draft):
    draft = make_draft()
    assert checks.card_contains(draft, "манометр dm 02 манотомь 0-1,6 мпа")
    assert not checks.card_contains(draft, "из нержавеющей стали")
