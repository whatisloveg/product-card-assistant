"""Карточка в виде Markdown и простого текста — чтобы скопировать и вставить в CMS."""

from __future__ import annotations

from .models import ProductCard


def _md_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def to_markdown(card: ProductCard) -> str:
    lines = [f"# {card.seo_title}", "", card.seo_description, "", "## Характеристики", ""]
    lines += ["| Характеристика | Значение |", "|---|---|"]
    lines += [f"| {_md_cell(s.name)} | {_md_cell(s.value)} |" for s in card.specs]
    lines += ["", "## Поисковые запросы", ""]
    lines += [f"- {q}" for q in card.search_queries]
    lines += ["", "## Для менеджера", "", "**Кому подходит:**", ""]
    lines += [f"- {a}" for a in card.commercial.audience]
    lines += ["", "**Какие задачи решает:**", ""]
    lines += [f"- {t}" for t in card.commercial.tasks]
    lines += ["", card.commercial.summary]
    if card.missing:
        lines += ["", "## Требует уточнения", ""]
        lines += [f"- **{m.name}** — {m.why}" for m in card.missing]
    if card.warnings:
        lines += ["", "## Проверьте вручную", ""]
        lines += [f"- {w}" for w in card.warnings]
    return "\n".join(lines) + "\n"


def to_text(card: ProductCard) -> str:
    width = max((len(s.name) for s in card.specs), default=0)
    lines = [
        "SEO-ЗАГОЛОВОК", card.seo_title, "",
        "SEO-ОПИСАНИЕ", card.seo_description, "",
        "ХАРАКТЕРИСТИКИ",
        *[f"{s.name.ljust(width)}  {s.value}" for s in card.specs], "",
        "ПОИСКОВЫЕ ЗАПРОСЫ", *card.search_queries, "",
        "ДЛЯ МЕНЕДЖЕРА",
        "Кому подходит: " + "; ".join(card.commercial.audience),
        "Какие задачи решает: " + "; ".join(card.commercial.tasks),
        card.commercial.summary,
    ]
    if card.missing:
        lines += ["", "ТРЕБУЕТ УТОЧНЕНИЯ", *[f"- {m.name}: {m.why}" for m in card.missing]]
    if card.warnings:
        lines += ["", "ПРОВЕРЬТЕ ВРУЧНУЮ", *[f"- {w}" for w in card.warnings]]
    return "\n".join(lines) + "\n"
