from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Sequence

from src.books.normalization import canonicalize_product_url
from src.books.parser import SOURCE
from src.storage.database import create_database_engine, create_session_factory
from src.storage.repositories import find_book_row, list_book_history_rows, row_to_current_state
from src.storage.service import persist_book_url


class CliError(RuntimeError):
    pass


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: _json_value(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _print_json(payload: Any) -> None:
    print(json.dumps(_json_value(payload), indent=2, sort_keys=True))


def _resolve_database_url(explicit: str | None) -> str:
    database_url = explicit or os.getenv("DATABASE_URL")
    if not database_url:
        raise CliError(
            "DATABASE_URL is required; set it in the environment or pass --database-url"
        )
    return database_url


def _canonical_identity(url: str) -> str:
    canonical = canonicalize_product_url(url)
    if canonical is None:
        raise CliError(f"invalid product URL: {url}")
    return canonical


def _open_session_factory(database_url: str):
    engine = create_database_engine(database_url)
    return engine, create_session_factory(engine)


def _command_scrape(args: argparse.Namespace) -> int:
    database_url = _resolve_database_url(args.database_url)
    engine, session_factory = _open_session_factory(database_url)
    try:
        result = persist_book_url(session_factory, args.url)
        payload = {
            "decision": result.transition.decision,
            "validation_errors": result.transition.validation_errors,
            "evidence_id": result.evidence.id,
            "observation_id": result.observation_id,
            "book_id": result.book_id,
            "current_state": result.transition.current_state,
        }
        _print_json(payload)
        return 0
    finally:
        engine.dispose()


def _command_show(args: argparse.Namespace) -> int:
    database_url = _resolve_database_url(args.database_url)
    canonical_url = _canonical_identity(args.url)
    engine, session_factory = _open_session_factory(database_url)
    try:
        with session_factory() as session:
            row = find_book_row(
                session,
                source=SOURCE,
                canonical_product_url=canonical_url,
            )
            if row is None:
                raise CliError(f"book not found for URL: {canonical_url}")
            _print_json(row_to_current_state(row))
        return 0
    finally:
        engine.dispose()


def _command_history(args: argparse.Namespace) -> int:
    database_url = _resolve_database_url(args.database_url)
    canonical_url = _canonical_identity(args.url)
    engine, session_factory = _open_session_factory(database_url)
    try:
        with session_factory() as session:
            book = find_book_row(
                session,
                source=SOURCE,
                canonical_product_url=canonical_url,
            )
            if book is None:
                raise CliError(f"book not found for URL: {canonical_url}")

            history = [
                {
                    "id": row.id,
                    "observation_id": row.observation_id,
                    "decision": row.decision,
                    "previous_state": row.previous_state,
                    "new_state": row.new_state,
                    "changed_at": row.changed_at,
                }
                for row in list_book_history_rows(session, book_id=book.id)
            ]
            _print_json(history)
        return 0
    finally:
        engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="data-scraper",
        description="Books M0 command-line interface",
    )
    parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL; defaults to DATABASE_URL",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    scrape = subparsers.add_parser(
        "scrape",
        help="fetch one Books to Scrape product and persist the resulting state decision",
    )
    scrape.add_argument("url")
    scrape.set_defaults(handler=_command_scrape)

    show = subparsers.add_parser(
        "show",
        help="show the current trusted state for one book URL",
    )
    show.add_argument("url")
    show.set_defaults(handler=_command_show)

    history = subparsers.add_parser(
        "history",
        help="show accepted state-transition history for one book URL",
    )
    history.add_argument("url")
    history.set_defaults(handler=_command_history)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except CliError as exc:
        parser.exit(2, f"error: {exc}\n")


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
