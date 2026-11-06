"""Командная строка: веб-сервер и пакетная генерация карточек из JSON-файлов."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pydantic

from . import render
from .config import Settings
from .llm import AnthropicClient, LLMError
from .models import ProductInput
from .service import CardService, InsufficientDataError


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    Settings.from_env()  # падаем сразу, если настройки некорректны
    uvicorn.run("card_assistant.api:app", host=args.host, port=args.port)
    return 0


def _generate(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    service = CardService(AnthropicClient(settings), settings)
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    failed = 0
    for path in args.files:
        try:
            product = ProductInput.model_validate_json(path.read_text(encoding="utf-8"))
            card = service.generate(product)
        except pydantic.ValidationError as exc:
            print(f"✗ {path}: некорректные входные данные\n{exc}", file=sys.stderr)
        except (InsufficientDataError, LLMError) as exc:
            print(f"✗ {path}: {exc}", file=sys.stderr)
        else:
            (out_dir / f"{path.stem}.json").write_text(
                json.dumps(card.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            (out_dir / f"{path.stem}.md").write_text(render.to_markdown(card), encoding="utf-8")
            print(
                f"✓ {path.name}: заголовок {card.meta.title_length} симв., описание "
                f"{card.meta.description_length} симв., попыток {card.meta.attempts}, "
                f"предупреждений {len(card.warnings)}, {card.meta.elapsed_sec} с"
            )
            continue
        failed += 1
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="python -m card_assistant", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="запустить веб-форму и API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(handler=_serve)

    generate = commands.add_parser("generate", help="сделать карточки из JSON-файлов")
    generate.add_argument("files", nargs="+", type=Path, help="файлы с данными о товарах")
    generate.add_argument("--out", type=Path, default=Path("examples/output"), help="куда сохранить результат")
    generate.set_defaults(handler=_generate)

    args = parser.parse_args(argv)
    return args.handler(args)
