"""Настройки из переменных окружения и файла .env (ключ API в коде не хранится)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")


def load_dotenv(path: Path = PROJECT_ROOT / ".env") -> None:
    """Минимальный загрузчик .env: KEY=VALUE, комментарии через #. Уже заданные переменные не трогает."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split(" #", 1)[0]  # комментарий в конце строки
        key, value = key.strip().removeprefix("export ").strip(), value.strip().strip("'\"")
        os.environ.setdefault(key, value)


def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on", "да"}


@dataclass(frozen=True)
class Settings:
    model: str = "claude-opus-5-5"
    effort: str = "medium"
    verify: bool = True
    max_repairs: int = 2
    timeout_sec: float = 180.0
    refusal_fallback: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        effort = os.environ.get("CARD_EFFORT", cls.effort).strip().lower()
        if effort not in EFFORT_LEVELS:
            raise ValueError(f"CARD_EFFORT должен быть одним из {', '.join(EFFORT_LEVELS)}, а не «{effort}»")
        return cls(
            model=os.environ.get("CARD_MODEL", cls.model).strip(),
            effort=effort,
            verify=_flag("CARD_VERIFY", cls.verify),
            max_repairs=int(os.environ.get("CARD_MAX_REPAIRS", cls.max_repairs)),
            timeout_sec=float(os.environ.get("CARD_TIMEOUT", cls.timeout_sec)),
            refusal_fallback=_flag("CARD_REFUSAL_FALLBACK", cls.refusal_fallback),
        )

    @property
    def api_key_configured(self) -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
