from __future__ import annotations

import argparse
import json
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .export import export_current_products


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Data-scraper delivery tools")
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="SQLAlchemy database URL; defaults to DATABASE_URL",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export-products", help="export trusted current products")
    export.add_argument("--format", choices=("json", "csv"), required=True)
    export.add_argument("--output", required=True)
    export.add_argument("--source")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.database_url:
        raise SystemExit("--database-url or DATABASE_URL is required")

    engine = create_engine(args.database_url, future=True)
    try:
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        if args.command == "export-products":
            result = export_current_products(
                factory,
                output_path=args.output,
                format=args.format,
                source=args.source,
            )
            print(
                json.dumps(
                    {
                        "format": result.format,
                        "output_path": str(result.output_path),
                        "records": result.records,
                        "source": result.source,
                    },
                    sort_keys=True,
                )
            )
            return 0
        raise SystemExit(f"unknown command: {args.command}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
