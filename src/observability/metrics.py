from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.storage.models import ScrapeRunRow


@dataclass(frozen=True)
class RunMetricsSnapshot:
    source: str | None
    scope_key: str | None
    since: datetime | None
    runs_total: int
    runs_running: int
    runs_succeeded: int
    runs_failed: int
    terminal_runs: int
    success_rate: float | None
    accounting_incomplete: int
    retries: int
    abandoned_runs: int
    duration_samples: int
    average_duration_seconds: float | None
    max_duration_seconds: float | None
    records_seen: int
    records_created: int
    records_updated: int
    records_no_change: int
    records_stale: int
    records_rejected: int
    records_disappeared: int
    records_reappeared: int
    failures_by_code: dict[str, int]

    def to_dict(self) -> dict:
        data = asdict(self)
        if self.since is not None:
            data["since"] = self.since.isoformat()
        return data


def _duration_seconds(row: ScrapeRunRow) -> float | None:
    if row.finished_at is None:
        return None
    value = (row.finished_at - row.started_at).total_seconds()
    return max(0.0, float(value))


def _snapshot_from_rows(
    rows: Iterable[ScrapeRunRow],
    *,
    source: str | None,
    scope_key: str | None,
    since: datetime | None,
) -> RunMetricsSnapshot:
    rows = tuple(rows)
    running = sum(row.status == "RUNNING" for row in rows)
    succeeded = sum(row.status == "SUCCEEDED" for row in rows)
    failed = sum(row.status == "FAILED" for row in rows)
    terminal = succeeded + failed

    complete_rows = tuple(row for row in rows if row.accounting_complete)
    durations = tuple(
        duration
        for row in rows
        if (duration := _duration_seconds(row)) is not None
    )

    failures_by_code: dict[str, int] = {}
    for row in rows:
        if row.status != "FAILED" or not row.error_code:
            continue
        failures_by_code[row.error_code] = failures_by_code.get(row.error_code, 0) + 1

    return RunMetricsSnapshot(
        source=source,
        scope_key=scope_key,
        since=since,
        runs_total=len(rows),
        runs_running=running,
        runs_succeeded=succeeded,
        runs_failed=failed,
        terminal_runs=terminal,
        success_rate=(succeeded / terminal) if terminal else None,
        accounting_incomplete=sum(not row.accounting_complete for row in rows),
        retries=sum(row.retry_of_run_id is not None for row in rows),
        abandoned_runs=sum(row.error_code == "RUN_ABANDONED" for row in rows),
        duration_samples=len(durations),
        average_duration_seconds=(sum(durations) / len(durations)) if durations else None,
        max_duration_seconds=max(durations) if durations else None,
        records_seen=sum(row.records_seen for row in complete_rows),
        records_created=sum(row.records_created for row in complete_rows),
        records_updated=sum(row.records_updated for row in complete_rows),
        records_no_change=sum(row.records_no_change for row in complete_rows),
        records_stale=sum(row.records_stale for row in complete_rows),
        records_rejected=sum(row.records_rejected for row in complete_rows),
        records_disappeared=sum(row.records_disappeared for row in complete_rows),
        records_reappeared=sum(row.records_reappeared for row in complete_rows),
        failures_by_code=dict(sorted(failures_by_code.items())),
    )


def collect_run_metrics(
    session_factory: sessionmaker[Session],
    *,
    source: str | None = None,
    scope_key: str | None = None,
    since: datetime | None = None,
) -> RunMetricsSnapshot:
    """Read an operational metrics snapshot from durable M14/M15 ScrapeRun rows.

    Product state/history is never queried or mutated. Counters are summed only from
    rows with accounting_complete=true, so abandoned/exception runs cannot fabricate
    proven business-work totals.
    """

    stmt = select(ScrapeRunRow).order_by(ScrapeRunRow.id)
    if source is not None:
        stmt = stmt.where(ScrapeRunRow.source == source)
    if scope_key is not None:
        stmt = stmt.where(ScrapeRunRow.scope_key == scope_key)
    if since is not None:
        stmt = stmt.where(ScrapeRunRow.started_at >= since)

    with session_factory() as session:
        rows = tuple(session.scalars(stmt))
    return _snapshot_from_rows(
        rows,
        source=source,
        scope_key=scope_key,
        since=since,
    )
