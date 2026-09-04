from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.catalogs.models import CatalogRunStatus
from src.products.models import StateDecision
from src.runs.models import ScrapeRunStatus, ScrapeRunTrigger
from src.runs.service import execute_catalog_operation
from src.storage.models import ScrapeRunRow
from src.storage.service import CatalogPersistenceResult


def _factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ScrapeRunRow.__table__.create(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _observed(decision: StateDecision):
    return SimpleNamespace(transition=SimpleNamespace(decision=decision))


def test_m14_successful_scheduled_run_is_terminal_and_counted():
    factory = _factory()
    catalog_result = CatalogPersistenceResult(
        catalog_run_id=12,
        coverage_status=CatalogRunStatus.COMPLETE,
        observed_results=(
            _observed(StateDecision.CREATE),
            _observed(StateDecision.NO_CHANGE),
        ),
        absence_transitions=(SimpleNamespace(decision=StateDecision.DISAPPEARED),),
    )

    result = execute_catalog_operation(
        factory,
        source="m14_source",
        scope_key="default",
        trigger=ScrapeRunTrigger.SCHEDULED,
        operation=lambda: catalog_result,
    )

    assert result.status == ScrapeRunStatus.SUCCEEDED
    with factory() as session:
        row = session.scalar(select(ScrapeRunRow))
        assert row is not None
        assert row.status == "SUCCEEDED"
        assert row.trigger_type == "SCHEDULED"
        assert row.finished_at is not None
        assert row.records_seen == 2
        assert row.records_created == 1
        assert row.records_no_change == 1
        assert row.records_disappeared == 1


def test_m14_incomplete_catalog_is_failed_without_undoing_accounting():
    factory = _factory()
    catalog_result = CatalogPersistenceResult(
        catalog_run_id=13,
        coverage_status=CatalogRunStatus.INCOMPLETE,
        observed_results=(_observed(StateDecision.UPDATE),),
        absence_transitions=(),
    )

    result = execute_catalog_operation(
        factory,
        source="m14_source",
        scope_key="default",
        operation=lambda: catalog_result,
    )

    assert result.status == ScrapeRunStatus.FAILED
    assert result.error_code == "CATALOG_INCOMPLETE"
    with factory() as session:
        row = session.scalar(select(ScrapeRunRow))
        assert row is not None
        assert row.status == "FAILED"
        assert row.records_seen == 1
        assert row.records_updated == 1
        assert row.error_code == "CATALOG_INCOMPLETE"


def test_m14_exception_marks_run_failed_and_re_raises():
    factory = _factory()

    def explode():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        execute_catalog_operation(
            factory,
            source="m14_source",
            scope_key="default",
            operation=explode,
        )

    with factory() as session:
        row = session.scalar(select(ScrapeRunRow))
        assert row is not None
        assert row.status == "FAILED"
        assert row.finished_at is not None
        assert row.error_code == "RuntimeError"
        assert row.error_message == "boom"
