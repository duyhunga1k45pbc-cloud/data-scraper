from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .metrics import collect_run_metrics


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Data-scraper operational observability")
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="SQLAlchemy database URL; defaults to DATABASE_URL",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    metrics = sub.add_parser("run-metrics", help="summarize durable scrape-run metrics")
    metrics.add_argument("--source")
    metrics.add_argument("--scope-key")
    metrics.add_argument("--since-hours", type=float)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.database_url:
        raise SystemExit("--database-url or DATABASE_URL is required")

    since = None
    if args.since_hours is not None:
        if args.since_hours < 0:
            raise SystemExit("--since-hours must be >= 0")
        since = datetime.now(timezone.utc) - timedelta(hours=args.since_hours)

    engine = create_engine(args.database_url, future=True)
    try:
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        snapshot = collect_run_metrics(
            factory,
            source=args.source,
            scope_key=args.scope_key,
            since=since,
        )
        print(json.dumps(snapshot.to_dict(), indent=2, sort_keys=True))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
