from __future__ import annotations

import argparse
import json

from .acquisition import HttpxPageLoader, acquire_web_scraping_dev_catalog


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Acquire web-scraping.dev through the existing M9 catalog proof boundary."
    )
    parser.add_argument("--max-catalog-pages", type=int, default=20)
    parser.add_argument("--max-products", type=int, default=200)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    args = parser.parse_args()

    acquisition = acquire_web_scraping_dev_catalog(
        load_page=HttpxPageLoader(timeout_seconds=args.timeout_seconds),
        max_catalog_pages=args.max_catalog_pages,
        max_products=args.max_products,
    )
    payload = {
        "source": acquisition.source,
        "scope_key": acquisition.scope_key,
        "coverage_status": acquisition.coverage_status.value,
        "chunks": len(acquisition.chunks),
        "evidence": len(acquisition.evidence),
        "observations": len(acquisition.observations),
        "terminal_status": acquisition.chunks[-1].status.value if acquisition.chunks else None,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
