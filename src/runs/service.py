from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select
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
    retry_of_run_id: int | None = None,
) -> tuple[int, int]:
    with session_factory() as session:
        with session.begin():
            attempt = 1
            if retry_of_run_id is not None:
                parent = session.scalar(
                    select(ScrapeRunRow)
                    .where(ScrapeRunRow.id == retry_of_run_id)
                    .with_for_update()
                )
                if parent is None:
                    raise ValueError(f"retry parent scrape run {retry_of_run_id} does not exist")
                if parent.status != ScrapeRunStatus.FAILED.value:
                    raise ValueError(
                        f"scrape run {retry_of_run_id} is {parent.status}; only FAILED runs may be retried"
                    )
                if parent.source != source or parent.scope_key != scope_key:
                    raise ValueError(
                        "retry source/scope must match the failed parent run"
                    )
                existing_retry = session.scalar(
                    select(ScrapeRunRow.id).where(
                        ScrapeRunRow.retry_of_run_id == retry_of_run_id
                    )
                )
                if existing_retry is not None:
                    raise ValueError(
                        f"scrape run {retry_of_run_id} already has retry run {existing_retry}"
                    )
                attempt = parent.attempt + 1

            row = ScrapeRunRow(
                source=source,
                scope_key=scope_key,
                trigger_type=_trigger_value(trigger),
                started_at=_utcnow(),
                finished_at=None,
                status=ScrapeRunStatus.RUNNING.value,
                retry_of_run_id=retry_of_run_id,
                attempt=attempt,
                accounting_complete=False,
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
            return row.id, attempt


def _finish_run(
    session_factory: sessionmaker[Session],
    *,
    run_id: int,
    status: ScrapeRunStatus,
    counters: RunCounters,
    accounting_complete: bool,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    with session_factory() as session:
        with session.begin():
            row = session.scalar(
                select(ScrapeRunRow)
                .where(ScrapeRunRow.id == run_id)
                .with_for_update()
            )
            if row is None:
                raise RuntimeError(f"scrape run {run_id} disappeared before finalization")
            if row.status != ScrapeRunStatus.RUNNING.value:
                raise RuntimeError(
                    f"scrape run {run_id} already terminal with status {row.status}"
                )
            row.finished_at = _utcnow()
            row.status = status.value
            row.accounting_complete = accounting_complete
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


def mark_abandoned_runs_failed(
    session_factory: sessionmaker[Session],
    *,
    started_before: datetime,
    source: str | None = None,
    scope_key: str | None = None,
    detected_at: datetime | None = None,
) -> tuple[int, ...]:
    """Operator-declare old RUNNING rows abandoned and terminalize them.

    M15 intentionally does not guess that a process is dead from elapsed time alone.
    The caller supplies the cutoff. Only scrape_runs is changed; trusted product state,
    RawEvidence, catalog coverage, observations, and semantic history are untouched.

    Because a hard crash can happen after partial durable work but before M14 receives
    a CatalogPersistenceResult, recovered rows keep ``accounting_complete = False``.
    Zero counters on such a row therefore never claim that zero product work occurred.
    """

    terminal_at = detected_at or _utcnow()
    with session_factory() as session:
        with session.begin():
            stmt = (
                select(ScrapeRunRow)
                .where(
                    ScrapeRunRow.status == ScrapeRunStatus.RUNNING.value,
                    ScrapeRunRow.started_at < started_before,
                )
                .order_by(ScrapeRunRow.id)
                .with_for_update()
            )
            if source is not None:
                stmt = stmt.where(ScrapeRunRow.source == source)
            if scope_key is not None:
                stmt = stmt.where(ScrapeRunRow.scope_key == scope_key)

            rows = tuple(session.scalars(stmt))
            for row in rows:
                row.finished_at = terminal_at
                row.status = ScrapeRunStatus.FAILED.value
                row.accounting_complete = False
                row.error_code = "RUN_ABANDONED"
                row.error_message = (
                    "operator marked RUNNING execution abandoned after cutoff "
                    f"{started_before.isoformat()}; counters may be incomplete"
                )
            return tuple(row.id for row in rows)


def execute_catalog_operation(
    session_factory: sessionmaker[Session],
    *,
    source: str,
    scope_key: str,
    operation: Callable[[], CatalogPersistenceResult],
    trigger: ScrapeRunTrigger | str = ScrapeRunTrigger.MANUAL,
    retry_of_run_id: int | None = None,
) -> ScrapeRunResult:
    """Run one catalog operation under durable operational lifecycle accounting.

    A returned CatalogPersistenceResult gives complete M14 accounting. An exception
    can occur after partial durable work but before that envelope exists, so exception
    failures are terminal FAILED with ``accounting_complete = False``.
    """

    run_id, attempt = _start_run(
        session_factory,
        source=source,
        scope_key=scope_key,
        trigger=trigger,
        retry_of_run_id=retry_of_run_id,
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
            accounting_complete=True,
            error_code=error_code,
            error_message=error_message,
        )
        return ScrapeRunResult(
            run_id=run_id,
            status=status,
            counters=counters,
            catalog_result=result,
            retry_of_run_id=retry_of_run_id,
            attempt=attempt,
            accounting_complete=True,
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
            accounting_complete=False,
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
    retry_of_run_id: int | None = None,
) -> ScrapeRunResult:
    """Acquire from the beginning, then pass evidence through M0-M14.

    M15 retry is intentionally whole-run retry, not chunk-level resume. Existing
    M0-M13 semantic idempotence protects trusted state when equivalent observations
    are reprocessed. Durable acquisition cursors are deferred until a real source
    demonstrates that restarting acquisition is insufficient.
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
        retry_of_run_id=retry_of_run_id,
    )


def _retry_parent_identity(
    session_factory: sessionmaker[Session],
    failed_run_id: int,
) -> tuple[str, str]:
    with session_factory() as session:
        parent = session.get(ScrapeRunRow, failed_run_id)
        if parent is None:
            raise ValueError(f"retry parent scrape run {failed_run_id} does not exist")
        if parent.status != ScrapeRunStatus.FAILED.value:
            raise ValueError(
                f"scrape run {failed_run_id} is {parent.status}; only FAILED runs may be retried"
            )
        return parent.source, parent.scope_key


def retry_catalog_operation(
    session_factory: sessionmaker[Session],
    *,
    failed_run_id: int,
    operation: Callable[[], CatalogPersistenceResult],
    trigger: ScrapeRunTrigger | str = ScrapeRunTrigger.MANUAL,
) -> ScrapeRunResult:
    source, scope_key = _retry_parent_identity(session_factory, failed_run_id)
    return execute_catalog_operation(
        session_factory,
        source=source,
        scope_key=scope_key,
        operation=operation,
        trigger=trigger,
        retry_of_run_id=failed_run_id,
    )


def retry_catalog_acquisition(
    session_factory: sessionmaker[Session],
    *,
    failed_run_id: int,
    acquisition: Callable[[], CatalogAcquisition],
    trigger: ScrapeRunTrigger | str = ScrapeRunTrigger.MANUAL,
    changed_at: datetime | None = None,
) -> ScrapeRunResult:
    source, scope_key = _retry_parent_identity(session_factory, failed_run_id)
    return execute_catalog_acquisition(
        session_factory,
        source=source,
        scope_key=scope_key,
        acquisition=acquisition,
        trigger=trigger,
        changed_at=changed_at,
        retry_of_run_id=failed_run_id,
    )
