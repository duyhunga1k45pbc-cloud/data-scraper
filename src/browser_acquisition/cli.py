from __future__ import annotations

import argparse
import json

from .probe import probe_js_link_discovery

DEFAULT_JS_LINKS_URL = "https://web-scraping.dev/js-links"


def main() -> int:
    parser = argparse.ArgumentParser(description="M18 Playwright acquisition probes")
    sub = parser.add_subparsers(dest="command", required=True)

    js = sub.add_parser(
        "probe-js-links",
        help="prove that JavaScript adds discoverable links after navigation",
    )
    js.add_argument("--url", default=DEFAULT_JS_LINKS_URL)
    js.add_argument("--timeout-ms", type=int, default=15_000)
    js.add_argument("--settle-ms", type=int, default=500)
    js.add_argument("--headed", action="store_true")

    args = parser.parse_args()
    if args.command == "probe-js-links":
        result = probe_js_link_discovery(
            args.url,
            timeout_ms=args.timeout_ms,
            settle_ms=args.settle_ms,
            headless=not args.headed,
        )
        body = {
            "requested_url": result.requested_url,
            "final_url": result.final_url,
            "status_code": result.status_code,
            "initial_link_count": len(result.initial_hrefs),
            "rendered_link_count": len(result.rendered_hrefs),
            "added_hrefs": result.added_hrefs,
            "js_added_links": result.js_added_links,
        }
        print(json.dumps(body, indent=2, sort_keys=True))
        return 0 if result.js_added_links else 2

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
