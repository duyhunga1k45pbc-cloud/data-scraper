import json
import logging
from datetime import datetime, timezone

from src.observability.events import build_event, emit_event


class RaisingLogger:
    def log(self, level, message):
        raise RuntimeError("sink unavailable")


class CaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def test_m16_build_event_is_json_safe_and_reserved_fields_are_owned():
    at = datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc)
    event = build_event(
        "scrape_run_started",
        emitted_at=at,
        run_id=7,
        source="scrapify_js",
    )
    assert event == {
        "event": "scrape_run_started",
        "emitted_at": at.isoformat(),
        "run_id": 7,
        "source": "scrapify_js",
    }
    assert json.loads(json.dumps(event))["run_id"] == 7


def test_m16_emit_event_contains_sink_failure():
    assert emit_event("scrape_run_started", logger=RaisingLogger(), run_id=1) is False


def test_m16_emit_event_writes_one_json_line():
    logger = logging.Logger("m16-test")
    handler = CaptureHandler()
    logger.addHandler(handler)
    assert emit_event("scrape_run_finished", logger=logger, run_id=9, status="SUCCEEDED")
    assert len(handler.messages) == 1
    payload = json.loads(handler.messages[0])
    assert payload["event"] == "scrape_run_finished"
    assert payload["run_id"] == 9
    assert payload["status"] == "SUCCEEDED"
