from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Sequence

from src.products.normalization import canonicalize_product_url
from src.products.source import UnsupportedSourceError, source_for_url
from src.scrapify_js.service import persist_catalog as persist_scrapify_catalog
from src.storage.database import create_database_engine, create_session_factory
from src.storage.repositories import (
    find_product_row,
    list_product_history_rows,
    row_to_current_state,
)
from src.storage.service import persist_product_url


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


def _canonical_identity(url: str) -> tuple[str, str]:
    try:
        source = source_for_url(url)
    except UnsupportedSourceError as exc:
        raise CliError(str(exc)) from exc

    canonical = canonicalize_product_url(url)
    if canonical is None:
        raise CliError(f"invalid product URL: {url}")
    return source, canonical


def _open_session_factory(database_url: str):
    engine = create_database_engine(database_url)
    return engine, create_session_factory(engine)


def _history_payload(rows) -> list[dict[str, Any]]:
    return [
        {
            "id": row.id,
            "observation_id": row.observation_id,
            "decision": row.decision,
            "previous_state": row.previous_state,
            "new_state": row.new_state,
            "changed_at": row.changed_at,
        }
        for row in rows
    ]


def _command_scrape(args: argparse.Namespace) -> int:
    database_url = _resolve_database_url(args.database_url)
    try:
        source_for_url(args.url)
    except UnsupportedSourceError as exc:
        raise CliError(str(exc)) from exc

    engine, session_factory = _open_session_factory(database_url)
    try:
        result = persist_product_url(session_factory, args.url)
        payload = {
            "decision": result.transition.decision,
            "validation_errors": result.transition.validation_errors,
            "evidence_id": result.evidence.id,
            "observation_id": result.observation_id,
            "product_id": result.product_id,
            "current_state": result.transition.current_state,
        }
        _print_json(payload)
        return 0
    finally:
        engine.dispose()


def _command_scrape_catalog(args: argparse.Namespace) -> int:
    database_url = _resolve_database_url(args.database_url)
    engine, session_factory = _open_session_factory(database_url)
    try:
        if args.source != "scrapify-js":
            raise CliError(f"unsupported M2 catalog source: {args.source}")

        results = persist_scrapify_catalog(session_factory)
        counts = Counter(run.transition.decision.value for run in results)
        payload = {
            "source": "scrapify_js",
            "records": len(results),
            "decisions": dict(sorted(counts.items())),
            "evidence_id": results[0].evidence.id if results else None,
            "product_ids": [run.product_id for run in results],
        }
        _print_json(payload)
        return 0
    finally:
        engine.dispose()


def _command_show(args: argparse.Namespace) -> int:
    database_url = _resolve_database_url(args.database_url)
    source, canonical_url = _canonical_identity(args.url)
    engine, session_factory = _open_session_factory(database_url)
    try:
        with session_factory() as session:
            row = find_product_row(
                session,
                source=source,
                canonical_product_url=canonical_url,
            )
            if row is None:
                raise CliError(f"product not found for URL: {canonical_url}")
            _print_json(row_to_current_state(row))
        return 0
    finally:
        engine.dispose()


def _command_history(args: argparse.Namespace) -> int:
    database_url = _resolve_database_url(args.database_url)
    source, canonical_url = _canonical_identity(args.url)
    engine, session_factory = _open_session_factory(database_url)
    try:
        with session_factory() as session:
            product = find_product_row(
                session,
                source=source,
                canonical_product_url=canonical_url,
            )
            if product is None:
                raise CliError(f"product not found for URL: {canonical_url}")
            _print_json(
                _history_payload(
                    list_product_history_rows(session, product_id=product.id)
                )
            )
        return 0
    finally:
        engine.dispose()


def _command_show_record(args: argparse.Namespace) -> int:
    database_url = _resolve_database_url(args.database_url)
    engine, session_factory = _open_session_factory(database_url)
    try:
        with session_factory() as session:
            row = find_product_row(
                session,
                source=args.source,
                source_record_id=args.record_id,
            )
            if row is None:
                raise CliError(
                    f"product not found for source record: {args.source}/{args.record_id}"
                )
            _print_json(row_to_current_state(row))
        return 0
    finally:
        engine.dispose()


def _command_history_record(args: argparse.Namespace) -> int:
    database_url = _resolve_database_url(args.database_url)
    engine, session_factory = _open_session_factory(database_url)
    try:
        with session_factory() as session:
            product = find_product_row(
                session,
                source=args.source,
                source_record_id=args.record_id,
            )
            if product is None:
                raise CliError(
                    f"product not found for source record: {args.source}/{args.record_id}"
                )
            _print_json(
                _history_payload(
                    list_product_history_rows(session, product_id=product.id)
                )
            )
        return 0
    finally:
        engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="data-scraper",
        description="M2 product scraper CLI (static product pages + JS storefront API)",
    )
    parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL; defaults to DATABASE_URL",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    scrape = subparsers.add_parser(
        "scrape",
        help="fetch one supported product URL and persist its state decision",
    )
    scrape.add_argument("url")
    scrape.set_defaults(handler=_command_scrape)

    scrape_catalog = subparsers.add_parser(
        "scrape-catalog",
        help="fetch and persist one supported multi-record catalog source",
    )
    scrape_catalog.add_argument("source", choices=["scrapify-js"])
    scrape_catalog.set_defaults(handler=_command_scrape_catalog)

    show = subparsers.add_parser(
        "show",
        help="show current trusted state for one URL-identified product",
    )
    show.add_argument("url")
    show.set_defaults(handler=_command_show)

    history = subparsers.add_parser(
        "history",
        help="show accepted history for one URL-identified product",
    )
    history.add_argument("url")
    history.set_defaults(handler=_command_history)

    show_record = subparsers.add_parser(
        "show-record",
        help="show current trusted state for a source-record-identified product",
    )
    show_record.add_argument("source")
    show_record.add_argument("record_id")
    show_record.set_defaults(handler=_command_show_record)

    history_record = subparsers.add_parser(
        "history-record",
        help="show history for a source-record-identified product",
    )
    history_record.add_argument("source")
    history_record.add_argument("record_id")
    history_record.set_defaults(handler=_command_history_record)

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
