"""Конвейер: черновик → проверки кодом → фактчекер-LLM → исправление → сборка карточки."""

from __future__ import annotations

import logging
import re
import time

from . import checks, prompts
from .config import Settings
from .llm import LLMClient
from .models import (
    NO_DATA,
    CardDraft,
    CardMeta,
    Issue,
    MissingItem,
    ProductCard,
    ProductInput,
    SpecItem,
    Verification,
)

log = logging.getLogger(__name__)


class InsufficientDataError(Exception):
    def __init__(self, missing: list[str]) -> None:
        super().__init__("Недостаточно данных для карточки: заполните характеристики или описание.")
        self.missing = missing


class CardService:
    def __init__(self, llm: LLMClient, settings: Settings) -> None:
        self._llm = llm
        self._settings = settings

    def generate(self, product: ProductInput) -> ProductCard:
        if not product.has_enough_data():
            raise InsufficientDataError(["Характеристики (specs)", "Описание (description)"])

        started = time.monotonic()
        calls = 1
        draft = self._llm.complete(prompts.GENERATION_SYSTEM, prompts.generation_prompt(product), CardDraft)
        issues: list[Issue] = []
        attempts = 1
        max_attempts = 1 + self._settings.max_repairs

        while True:
            # Сначала дешёвые проверки кодом; фактчекер-LLM — только когда они пройдены.
            issues = checks.run_all(draft, product)
            if not issues and self._settings.verify:
                issues = self._verify(product, draft)
                calls += 1
            if not issues or attempts >= max_attempts:
                break
            log.info("попытка %d, исправляем: %s", attempts, "; ".join(issue.message for issue in issues))
            draft = self._llm.complete(
                prompts.GENERATION_SYSTEM, prompts.repair_prompt(product, draft, issues), CardDraft
            )
            calls += 1
            attempts += 1

        return self._assemble(product, draft, issues, attempts, calls, time.monotonic() - started)

    def _verify(self, product: ProductInput, draft: CardDraft) -> list[Issue]:
        report = self._llm.complete(prompts.VERIFY_SYSTEM, prompts.verification_prompt(product, draft), Verification)
        issues = []
        for claim in report.unsupported:
            # Фактчекер тоже может ошибиться: принимаем только цитаты, которые реально есть в карточке.
            if not checks.card_contains(draft, claim.quote):
                log.info("фактчекер сослался на фрагмент, которого нет в карточке: %r", claim.quote)
                continue
            issues.append(Issue(
                code="unsupported_claim", field=claim.field,
                message=f"В поле {claim.field} утверждение «{claim.quote}» не подтверждается входными данными: "
                        f"{claim.reason}",
            ))
        return issues

    def _assemble(
        self, product: ProductInput, draft: CardDraft, issues: list[Issue],
        attempts: int, calls: int, elapsed: float,
    ) -> ProductCard:
        warnings = [issue.message for issue in issues]
        specs = []
        for spec in draft.specs:
            if checks.spec_is_grounded(spec, product):
                specs.append(spec)
            else:
                # Последний рубеж: в таблицу не попадает значение, которого нет во входных данных.
                specs.append(SpecItem(name=spec.name, value=NO_DATA, source=""))
                warnings.append(f"Значение «{spec.name}: {spec.value}» не подтвердилось и заменено на «{NO_DATA}».")
        specs += _dropped_input_specs(product, specs)

        return ProductCard(
            seo_title=draft.seo_title,
            seo_description=draft.seo_description,
            specs=specs,
            search_queries=[q.strip() for q in draft.search_queries if q.strip()],
            commercial=draft.commercial,
            missing=_merge_missing(product, draft.missing, specs),
            warnings=list(dict.fromkeys(warnings)),
            meta=CardMeta(
                model=self._llm.model,
                attempts=attempts,
                llm_calls=calls,
                elapsed_sec=round(elapsed, 1),
                title_length=len(draft.seo_title),
                description_length=len(draft.seo_description),
            ),
        )


def _dropped_input_specs(product: ProductInput, specs: list[SpecItem]) -> list[SpecItem]:
    """Характеристики из входа, которые модель потеряла, возвращаем в таблицу как есть."""
    present = {checks.normalize(s.value) for s in specs} | {checks.normalize(s.source) for s in specs}
    dropped = []
    for key, value in product.filled_specs.items():
        line = checks.normalize(f"{key}: {value}")
        if checks.normalize(value) not in present and not any(line in item for item in present):
            dropped.append(SpecItem(name=key[:1].upper() + key[1:], value=value, source=f"{key}: {value}"))
    return dropped


def _merge_missing(product: ProductInput, missing: list[MissingItem], specs: list[SpecItem]) -> list[MissingItem]:
    """К пунктам модели добавляем пустые поля входа и все «данных нет» из таблицы."""
    def key(name: str) -> frozenset[str]:
        # Пункт уже есть, если все его слова входят в другой: «Температура измеряемой среды»
        # покрыта «Температурой измеряемой и окружающей среды». Пояснения в скобках и после запятой не считаем.
        head = re.split(r"[(,]", checks.normalize(name), maxsplit=1)[0]
        return frozenset(re.findall(r"\w+", head))

    result = list(missing)
    known = [key(item.name) for item in result]

    def add(name: str, why: str) -> None:
        new = key(name)
        if not any(new <= other or other <= new for other in known):
            known.append(new)
            result.append(MissingItem(name=name, why=why))

    for field in product.empty_fields():
        add(field, "Поле пустое во входных данных.")
    for spec in specs:
        if spec.value == NO_DATA:
            add(spec.name, "Нет во входных данных, а покупателю это нужно для выбора прибора.")
    return result
