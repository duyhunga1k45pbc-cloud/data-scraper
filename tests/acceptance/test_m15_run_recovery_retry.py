from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.catalogs.models import CatalogRunStatus
from src.products.models import StateDecision
from src.runs.models import ScrapeRunStatus
from src.runs.service import (
    execute_catalog_operation,
    mark_abandoned_runs_failed,
    retry_catalog_operation,
)
from src.storage.models import ScrapeRunRow
from src.storage.service import CatalogPersistenceResult

T0 = datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc)


def _factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ScrapeRunRow.__table__.create(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _result(decision: StateDecision = StateDecision.NO_CHANGE):
    return CatalogPersistenceResult(
        catalog_run_id=77,
        coverage_status=CatalogRunStatus.COMPLETE,
        observed_results=(
            SimpleNamespace(transition=SimpleNamespace(decision=decision)),
        ),
        absence_transitions=(),
    )


def test_m15_operator_recovers_only_old_running_rows_without_fake_counters():
    factory = _factory()
    with factory() as session:
        with session.begin():
            old = ScrapeRunRow(
                source="m15", scope_key="default", trigger_type="SCHEDULED",
                started_at=T0, finished_at=None, status="RUNNING",
                retry_of_run_id=None, attempt=1, accounting_complete=False,
                records_seen=0, records_created=0, records_updated=0,
                records_no_change=0, records_stale=0, records_rejected=0,
                records_disappeared=0, records_reappeared=0,
                error_code=None, error_message=None,
            )
            fresh = ScrapeRunRow(
                source="m15", scope_key="default", trigger_type="SCHEDULED",
                started_at=T0 + timedelta(hours=3), finished_at=None, status="RUNNING",
                retry_of_run_id=None, attempt=1, accounting_complete=False,
                records_seen=0, records_created=0, records_updated=0,
                records_no_change=0, records_stale=0, records_rejected=0,
                records_disappeared=0, records_reappeared=0,
                error_code=None, error_message=None,
            )
            session.add_all([old, fresh])
            session.flush()
            old_id, fresh_id = old.id, fresh.id

    recovered = mark_abandoned_runs_failed(
        factory,
        started_before=T0 + timedelta(hours=2),
        detected_at=T0 + timedelta(hours=4),
    )
    assert recovered == (old_id,)

    with factory() as session:
        old = session.get(ScrapeRunRow, old_id)
        fresh = session.get(ScrapeRunRow, fresh_id)
        assert old.status == "FAILED"
        assert old.error_code == "RUN_ABANDONED"
        assert old.accounting_complete is False
        assert old.records_seen == 0
        assert fresh.status == "RUNNING"


def test_m15_retry_creates_new_linear_attempt_and_preserves_parent():
    factory = _factory()
    failed = execute_catalog_operation(
        factory,
        source="m15",
        scope_key="default",
        operation=lambda: CatalogPersistenceResult(
            catalog_run_id=1,
            coverage_status=CatalogRunStatus.INCOMPLETE,
            observed_results=(),
            absence_transitions=(),
        ),
    )
    assert failed.status == ScrapeRunStatus.FAILED
    assert failed.attempt == 1

    retried = retry_catalog_operation(
        factory,
        failed_run_id=failed.run_id,
        operation=_result,
    )
    assert retried.status == ScrapeRunStatus.SUCCEEDED
    assert retried.retry_of_run_id == failed.run_id
    assert retried.attempt == 2

    with factory() as session:
        parent = session.get(ScrapeRunRow, failed.run_id)
        child = session.get(ScrapeRunRow, retried.run_id)
        assert parent.status == "FAILED"
        assert parent.retry_of_run_id is None
        assert child.retry_of_run_id == parent.id
        assert child.attempt == 2
        assert child.accounting_complete is True


def test_m15_retry_rejects_succeeded_parent_and_duplicate_child():
    factory = _factory()
    succeeded = execute_catalog_operation(
        factory,
        source="m15",
        scope_key="default",
        operation=_result,
    )
    with pytest.raises(ValueError, match="only FAILED runs may be retried"):
        retry_catalog_operation(
            factory, failed_run_id=succeeded.run_id, operation=_result
        )

    failed = execute_catalog_operation(
        factory,
        source="m15",
        scope_key="default",
        operation=lambda: CatalogPersistenceResult(
            catalog_run_id=2, coverage_status=CatalogRunStatus.INCOMPLETE,
            observed_results=(), absence_transitions=(),
        ),
    )
    retry_catalog_operation(factory, failed_run_id=failed.run_id, operation=_result)
    with pytest.raises(ValueError, match="already has retry run"):
        retry_catalog_operation(factory, failed_run_id=failed.run_id, operation=_result)


def test_m15_exception_failure_does_not_claim_complete_accounting():
    factory = _factory()

    with pytest.raises(RuntimeError, match="boom"):
        execute_catalog_operation(
            factory, source="m15", scope_key="default",
            operation=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )

    with factory() as session:
        row = session.scalar(select(ScrapeRunRow))
        assert row.status == "FAILED"
        assert row.accounting_complete is False
        assert row.error_code == "RuntimeError"
