from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

LOGGER_NAME = "data_scraper.observability"
_RESERVED = {"event", "emitted_at"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    return value


def build_event(
    event: str,
    *,
    emitted_at: datetime | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Build one JSON-safe operational event.

    M16 events intentionally carry run metadata/counters only. Callers must not pass
    RawEvidence bodies, parsed payloads, product snapshots, or other business data.
    """

    if not event or not event.strip():
        raise ValueError("event name must not be empty")
    collision = _RESERVED.intersection(fields)
    if collision:
        names = ", ".join(sorted(collision))
        raise ValueError(f"reserved event fields cannot be overridden: {names}")

    payload: dict[str, Any] = {
        "event": event,
        "emitted_at": (emitted_at or _utcnow()).isoformat(),
    }
    for key, value in fields.items():
        payload[key] = _json_value(value)
    return payload


def emit_event(
    event: str,
    *,
    level: int = logging.INFO,
    logger: logging.Logger | None = None,
    emitted_at: datetime | None = None,
    **fields: Any,
) -> bool:
    """Best-effort JSON event emission.

    Observability is non-authoritative. A broken/misconfigured handler must never
    change scrape-run or trusted-product semantics, so logging failures are contained.
    """

    try:
        payload = build_event(event, emitted_at=emitted_at, **fields)
        target = logger or logging.getLogger(LOGGER_NAME)
        target.log(level, json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return True
    except Exception:
        return False
