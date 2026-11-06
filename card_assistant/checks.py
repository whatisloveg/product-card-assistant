"""Детерминированные проверки черновика: длины, числа, цитаты, рискованные обещания.

Модели нельзя верить на слово. Всё, что проверяется кодом, проверяется кодом:
каждое число в карточке должно встречаться во входных данных, каждая цитата
в таблице характеристик — быть подстрокой входных данных.
"""

from __future__ import annotations

import re

from .models import NO_DATA, CardDraft, Issue, ProductInput, SpecItem

TITLE_MAX = 70
DESCRIPTION_MIN = 800
DESCRIPTION_MAX = 1200
QUERIES_MIN = 3
QUERIES_MAX = 5

_DASHES = re.compile(r"[‐-―−]")
_SPACES = re.compile(r"[\s   ]+")
_QUOTES = re.compile(r"[«»„“”\"']")
_TIMES = re.compile(r"(?<=\d)\s*[хx×]\s*(?=\d)")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")

# Обещания, которые в B2B нельзя давать без данных: их чаще всего «дописывает» модель.
RISKY_CLAIMS: dict[str, re.Pattern[str]] = {
    "гарантия": re.compile(r"гаранти"),
    "поверка": re.compile(r"поверк|поверен|госреестр|реестр\w* си"),
    "сертификация": re.compile(r"сертифи"),
    "наличие": re.compile(r"в наличии|на складе"),
    "доставка": re.compile(r"доставк"),
    "цена": re.compile(r"\bцен[аеуы]?\b|стоимост|скидк|недорог|дешев"),
    "взрывозащита": re.compile(r"взрывозащ|\bex\b"),
    "степень защиты": re.compile(r"\bip\s?\d{2}\b"),
}


SERVICE_PHRASES = (
    "данных нет", "нет данных", "не указан", "входных данных", "исходных данных",
    "уточните", "уточнить", "уточняйте", "по паспорту",
)


def normalize(text: str) -> str:
    """Приводит текст к виду, в котором удобно искать совпадения."""
    text = text.lower().replace("ё", "е").replace("…", "...")
    text = _DASHES.sub("-", text)
    text = _QUOTES.sub("", text)
    text = _TIMES.sub("x", text)
    return _SPACES.sub(" ", text).strip()


def numbers(text: str) -> set[str]:
    """Числа в каноническом виде: «1,6» и «1.6» → «1.6», «02» → «2»."""
    result = set()
    for raw in _NUMBER.findall(text):
        value = float(raw.replace(",", "."))
        result.add(f"{value:g}")
    return result


def source_text(product: ProductInput) -> str:
    """Все входные данные одной строкой — это единственный источник фактов.

    Поля подписаны так же, как в JSON: модель цитирует и «name: …», и само название — подходят оба.
    """
    lines = [f"name: {product.name}"]
    if product.manufacturer:
        lines.append(f"manufacturer: {product.manufacturer}")
    lines += [f"{key}: {value}" for key, value in product.filled_specs.items()]
    if product.description:
        lines.append(f"description: {product.description}")
    return "\n".join(lines)


def _card_texts(draft: CardDraft) -> dict[str, str]:
    commercial = draft.commercial
    return {
        "seo_title": draft.seo_title,
        "seo_description": draft.seo_description,
        "search_queries": "\n".join(draft.search_queries),
        "commercial": "\n".join([*commercial.audience, *commercial.tasks, commercial.summary]),
        "specs": "\n".join(f"{s.name}: {s.value}" for s in draft.specs if s.value != NO_DATA),
    }


def card_contains(draft: CardDraft, quote: str) -> bool:
    """Есть ли такой фрагмент в карточке — так отсекаем «находки», которые фактчекер выдумал сам."""
    needle = normalize(quote)
    return bool(needle) and any(needle in normalize(text) for text in _card_texts(draft).values())


def check_lengths(draft: CardDraft) -> list[Issue]:
    issues = []
    title_len = len(draft.seo_title)
    if not draft.seo_title.strip():
        issues.append(Issue(code="title_empty", field="seo_title", message="SEO-заголовок пустой."))
    elif title_len > TITLE_MAX:
        issues.append(Issue(
            code="title_length", field="seo_title",
            message=f"SEO-заголовок длиной {title_len} символов, нужно не больше {TITLE_MAX}: "
                    f"сократи минимум на {title_len - TITLE_MAX}.",
        ))

    desc_len = len(draft.seo_description)
    if desc_len < DESCRIPTION_MIN:
        issues.append(Issue(
            code="description_length", field="seo_description",
            message=f"SEO-описание длиной {desc_len} символов, нужно {DESCRIPTION_MIN}–{DESCRIPTION_MAX}: "
                    f"добавь около {DESCRIPTION_MIN + 150 - desc_len} символов, не добавляя новых фактов.",
        ))
    elif desc_len > DESCRIPTION_MAX:
        issues.append(Issue(
            code="description_length", field="seo_description",
            message=f"SEO-описание длиной {desc_len} символов, нужно {DESCRIPTION_MIN}–{DESCRIPTION_MAX}: "
                    f"сократи примерно на {desc_len - DESCRIPTION_MAX + 100}.",
        ))

    queries = [q for q in draft.search_queries if q.strip()]
    if not QUERIES_MIN <= len(queries) <= QUERIES_MAX:
        issues.append(Issue(
            code="queries_count", field="search_queries",
            message=f"Поисковых запросов {len(queries)}, нужно {QUERIES_MIN}–{QUERIES_MAX}.",
        ))
    return issues


def check_numbers(draft: CardDraft, product: ProductInput) -> list[Issue]:
    """Любое число в карточке, которого нет во входных данных, — выдумка или пересчёт."""
    known = numbers(source_text(product))
    issues = []
    for field, text in _card_texts(draft).items():
        unknown = sorted(numbers(text) - known, key=float)
        if unknown:
            issues.append(Issue(
                code="unknown_number", field=field,
                message=f"В поле {field} есть числа, которых нет во входных данных: {', '.join(unknown)}. "
                        "Убери их или замени значениями из данных (без пересчёта единиц).",
            ))
    return issues


def spec_is_grounded(spec: SpecItem, product: ProductInput) -> bool:
    """Значение характеристики подтверждено, если цитата есть во входе и все числа значения — в цитате."""
    if spec.value.strip().lower() == NO_DATA:
        return True
    quote = normalize(spec.source)
    if not quote or quote not in normalize(source_text(product)):
        return False
    return numbers(spec.value) <= numbers(spec.source)


def check_specs(draft: CardDraft, product: ProductInput) -> list[Issue]:
    issues = []
    for spec in draft.specs:
        if not spec_is_grounded(spec, product):
            issues.append(Issue(
                code="spec_not_grounded", field="specs",
                message=f"Характеристика «{spec.name}: {spec.value}» не подтверждается цитатой из входных "
                        f"данных (source: «{spec.source}»). Дай дословную цитату или поставь «{NO_DATA}».",
            ))
    return issues


def check_customer_facing(draft: CardDraft) -> list[Issue]:
    """Заголовок и описание видит покупатель — служебным пометкам о нехватке данных там не место."""
    issues = []
    for field in ("seo_title", "seo_description"):
        text = normalize(getattr(draft, field))
        found = [phrase for phrase in SERVICE_PHRASES if phrase in text]
        if found:
            issues.append(Issue(
                code="service_text", field=field,
                message=f"В поле {field} есть служебные фразы для контент-менеджера ({', '.join(found)}). "
                        "Это текст для покупателя: убери их, а что уточнить — перенеси в missing.",
            ))
    return issues


def check_risky_claims(draft: CardDraft, product: ProductInput) -> list[Issue]:
    source = normalize(source_text(product))
    issues = []
    for field, text in _card_texts(draft).items():
        if field == "specs":
            continue  # таблицу проверяет check_specs
        text = normalize(text)
        for topic, pattern in RISKY_CLAIMS.items():
            if pattern.search(text) and not pattern.search(source):
                issues.append(Issue(
                    code="risky_claim", field=field,
                    message=f"В поле {field} упоминается «{topic}», но во входных данных об этом ничего нет. Убери.",
                ))
    return issues


def run_all(draft: CardDraft, product: ProductInput) -> list[Issue]:
    return [
        *check_lengths(draft),
        *check_customer_facing(draft),
        *check_numbers(draft, product),
        *check_specs(draft, product),
        *check_risky_claims(draft, product),
    ]
