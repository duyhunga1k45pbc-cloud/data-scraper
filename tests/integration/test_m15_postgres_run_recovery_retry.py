import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from src.catalogs.models import CatalogRunStatus
from src.products.models import StateDecision
from src.runs.service import mark_abandoned_runs_failed, retry_catalog_operation
from src.storage.models import ScrapeRunRow
from src.storage.service import CatalogPersistenceResult

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES") != "1",
    reason="set RUN_POSTGRES=1 to run PostgreSQL integration tests",
)


def test_m15_postgres_abandoned_recovery_and_retry_lineage():
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url, future=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    source = "m15_test_" + uuid.uuid4().hex
    t0 = datetime.now(timezone.utc) - timedelta(hours=3)

    try:
        with factory() as session:
            with session.begin():
                row = ScrapeRunRow(
                    source=source, scope_key="default", trigger_type="SCHEDULED",
                    started_at=t0, finished_at=None, status="RUNNING",
                    retry_of_run_id=None, attempt=1, accounting_complete=False,
                    records_seen=0, records_created=0, records_updated=0,
                    records_no_change=0, records_stale=0, records_rejected=0,
                    records_disappeared=0, records_reappeared=0,
                    error_code=None, error_message=None,
                )
                session.add(row)
                session.flush()
                parent_id = row.id

        recovered = mark_abandoned_runs_failed(
            factory,
            started_before=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        assert parent_id in recovered

        result = CatalogPersistenceResult(
            catalog_run_id=1,
            coverage_status=CatalogRunStatus.COMPLETE,
            observed_results=(
                SimpleNamespace(
                    transition=SimpleNamespace(decision=StateDecision.NO_CHANGE)
                ),
            ),
            absence_transitions=(),
        )
        child = retry_catalog_operation(
            factory, failed_run_id=parent_id, operation=lambda: result
        )
        assert child.attempt == 2
        assert child.retry_of_run_id == parent_id

        with factory() as session:
            parent = session.get(ScrapeRunRow, parent_id)
            retry = session.get(ScrapeRunRow, child.run_id)
            assert parent.status == "FAILED"
            assert parent.error_code == "RUN_ABANDONED"
            assert parent.accounting_complete is False
            assert retry.status == "SUCCEEDED"
            assert retry.accounting_complete is True
            assert retry.attempt == 2
            assert retry.retry_of_run_id == parent_id
    finally:
        with factory() as session:
            with session.begin():
                # One SQL DELETE removes the whole source-local retry chain in one
                # statement. ORM per-row deletes can be reordered/batched and may
                # attempt the RESTRICT parent before its child.
                session.execute(
                    delete(ScrapeRunRow).where(ScrapeRunRow.source == source)
                )
        engine.dispose()
