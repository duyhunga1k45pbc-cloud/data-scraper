from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy.orm import Session, sessionmaker

from src.catalogs.models import CatalogAcquisition, CatalogRunStatus
from src.storage.models import ScrapeRunRow
from src.storage.service import CatalogPersistenceResult, persist_catalog_acquisition_result

from .models import RunCounters, ScrapeRunResult, ScrapeRunStatus, ScrapeRunTrigger


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _trigger_value(trigger: ScrapeRunTrigger | str) -> str:
    if isinstance(trigger, ScrapeRunTrigger):
        return trigger.value
    return ScrapeRunTrigger(trigger).value


def _start_run(
    session_factory: sessionmaker[Session],
    *,
    source: str,
    scope_key: str,
    trigger: ScrapeRunTrigger | str,
) -> int:
    with session_factory() as session:
        with session.begin():
            row = ScrapeRunRow(
                source=source,
                scope_key=scope_key,
                trigger_type=_trigger_value(trigger),
                started_at=_utcnow(),
                finished_at=None,
                status=ScrapeRunStatus.RUNNING.value,
                records_seen=0,
                records_created=0,
                records_updated=0,
                records_no_change=0,
                records_stale=0,
                records_rejected=0,
                records_disappeared=0,
                records_reappeared=0,
                error_code=None,
                error_message=None,
            )
            session.add(row)
            session.flush()
            return row.id


def _finish_run(
    session_factory: sessionmaker[Session],
    *,
    run_id: int,
    status: ScrapeRunStatus,
    counters: RunCounters,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    with session_factory() as session:
        with session.begin():
            row = session.get(ScrapeRunRow, run_id)
            if row is None:
                raise RuntimeError(f"scrape run {run_id} disappeared before finalization")
            if row.status != ScrapeRunStatus.RUNNING.value:
                raise RuntimeError(
                    f"scrape run {run_id} already terminal with status {row.status}"
                )
            row.finished_at = _utcnow()
            row.status = status.value
            row.records_seen = counters.records_seen
            row.records_created = counters.records_created
            row.records_updated = counters.records_updated
            row.records_no_change = counters.records_no_change
            row.records_stale = counters.records_stale
            row.records_rejected = counters.records_rejected
            row.records_disappeared = counters.records_disappeared
            row.records_reappeared = counters.records_reappeared
            row.error_code = error_code
            row.error_message = error_message


def execute_catalog_operation(
    session_factory: sessionmaker[Session],
    *,
    source: str,
    scope_key: str,
    operation: Callable[[], CatalogPersistenceResult],
    trigger: ScrapeRunTrigger | str = ScrapeRunTrigger.MANUAL,
) -> ScrapeRunResult:
    """Run one catalog operation under durable operational lifecycle accounting.

    ScrapeRun is operational metadata only. Product truth remains in the existing
    RawEvidence/observation/history/current-state pipeline. An INCOMPLETE catalog
    acquisition is a FAILED operational run even though directly observed records
    may have been safely persisted by the M8/M9 rules.

    A hard process crash can leave RUNNING behind. Recovery/reaping of abandoned
    runs is intentionally deferred to M15.
    """

    run_id = _start_run(
        session_factory,
        source=source,
        scope_key=scope_key,
        trigger=trigger,
    )
    try:
        result = operation()
        counters = RunCounters.from_catalog_result(result)
        if result.coverage_status == CatalogRunStatus.COMPLETE:
            status = ScrapeRunStatus.SUCCEEDED
            error_code = None
            error_message = None
        else:
            status = ScrapeRunStatus.FAILED
            error_code = "CATALOG_INCOMPLETE"
            error_message = "catalog acquisition did not prove complete scope coverage"
        _finish_run(
            session_factory,
            run_id=run_id,
            status=status,
            counters=counters,
            error_code=error_code,
            error_message=error_message,
        )
        return ScrapeRunResult(
            run_id=run_id,
            status=status,
            counters=counters,
            catalog_result=result,
            error_code=error_code,
            error_message=error_message,
        )
    except Exception as exc:
        counters = RunCounters()
        error_code = type(exc).__name__
        error_message = str(exc)[:4000]
        _finish_run(
            session_factory,
            run_id=run_id,
            status=ScrapeRunStatus.FAILED,
            counters=counters,
            error_code=error_code,
            error_message=error_message,
        )
        raise


def execute_catalog_acquisition(
    session_factory: sessionmaker[Session],
    *,
    source: str,
    scope_key: str,
    acquisition: Callable[[], CatalogAcquisition],
    trigger: ScrapeRunTrigger | str = ScrapeRunTrigger.MANUAL,
    changed_at: datetime | None = None,
) -> ScrapeRunResult:
    """Start the run before acquisition, then pass acquired evidence to M0-M13.

    This is the entry point an external cron/systemd timer or manual source runner
    should call. The scheduler is only a trigger and never becomes source of truth.
    """

    def operation() -> CatalogPersistenceResult:
        acquired = acquisition()
        if acquired.source != source:
            raise ValueError(
                f"acquisition source {acquired.source!r} does not match run source {source!r}"
            )
        if acquired.scope_key != scope_key:
            raise ValueError(
                f"acquisition scope {acquired.scope_key!r} does not match run scope {scope_key!r}"
            )
        return persist_catalog_acquisition_result(
            session_factory,
            acquired,
            changed_at=changed_at,
        )

    return execute_catalog_operation(
        session_factory,
        source=source,
        scope_key=scope_key,
        operation=operation,
        trigger=trigger,
    )
