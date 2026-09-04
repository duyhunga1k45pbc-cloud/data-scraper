from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.observability.metrics import _snapshot_from_rows


def row(**overrides):
    base = dict(
        status="SUCCEEDED",
        accounting_complete=True,
        retry_of_run_id=None,
        error_code=None,
        started_at=datetime(2026, 9, 5, 10, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 9, 5, 10, 0, 10, tzinfo=timezone.utc),
        records_seen=10,
        records_created=1,
        records_updated=2,
        records_no_change=7,
        records_stale=0,
        records_rejected=0,
        records_disappeared=0,
        records_reappeared=0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_m16_metrics_exclude_unproven_counters_from_incomplete_runs():
    rows = (
        row(),
        row(
            status="FAILED",
            accounting_complete=False,
            error_code="RUN_ABANDONED",
            records_seen=999,
            records_created=999,
            finished_at=datetime(2026, 9, 5, 10, 1, tzinfo=timezone.utc),
        ),
        row(
            status="FAILED",
            accounting_complete=True,
            error_code="CATALOG_INCOMPLETE",
            retry_of_run_id=1,
            records_seen=4,
            records_created=0,
            records_updated=0,
            records_no_change=4,
            finished_at=datetime(2026, 9, 5, 10, 0, 5, tzinfo=timezone.utc),
        ),
        row(
            status="RUNNING",
            accounting_complete=False,
            finished_at=None,
            records_seen=123,
        ),
    )
    snapshot = _snapshot_from_rows(rows, source="x", scope_key=None, since=None)
    assert snapshot.runs_total == 4
    assert snapshot.runs_running == 1
    assert snapshot.runs_succeeded == 1
    assert snapshot.runs_failed == 2
    assert snapshot.terminal_runs == 3
    assert snapshot.success_rate == 1 / 3
    assert snapshot.accounting_incomplete == 2
    assert snapshot.retries == 1
    assert snapshot.abandoned_runs == 1
    assert snapshot.records_seen == 14
    assert snapshot.records_created == 1
    assert snapshot.failures_by_code == {
        "CATALOG_INCOMPLETE": 1,
        "RUN_ABANDONED": 1,
    }
    assert snapshot.duration_samples == 3
