import os
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from src.catalogs.models import CatalogRunStatus
from src.products.models import StateDecision
from src.runs.models import ScrapeRunStatus, ScrapeRunTrigger
from src.runs.service import execute_catalog_operation
from src.storage.models import ScrapeRunRow
from src.storage.service import CatalogPersistenceResult

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES") != "1",
    reason="set RUN_POSTGRES=1 to run PostgreSQL integration tests",
)


def test_m14_postgres_run_lifecycle_persists_terminal_accounting():
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url, future=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    source = "m14_test_" + uuid.uuid4().hex

    try:
        catalog_result = CatalogPersistenceResult(
            catalog_run_id=1,
            coverage_status=CatalogRunStatus.COMPLETE,
            observed_results=(
                SimpleNamespace(transition=SimpleNamespace(decision=StateDecision.CREATE)),
                SimpleNamespace(transition=SimpleNamespace(decision=StateDecision.STALE)),
            ),
            absence_transitions=(
                SimpleNamespace(decision=StateDecision.DISAPPEARED),
            ),
        )
        result = execute_catalog_operation(
            factory,
            source=source,
            scope_key="default",
            trigger=ScrapeRunTrigger.SCHEDULED,
            operation=lambda: catalog_result,
        )
        assert result.status == ScrapeRunStatus.SUCCEEDED

        with factory() as session:
            row = session.scalar(
                select(ScrapeRunRow).where(ScrapeRunRow.source == source)
            )
            assert row is not None
            assert row.status == "SUCCEEDED"
            assert row.records_seen == 2
            assert row.records_created == 1
            assert row.records_stale == 1
            assert row.records_disappeared == 1
    finally:
        with factory() as session:
            with session.begin():
                session.execute(
                    delete(ScrapeRunRow).where(ScrapeRunRow.source == source)
                )
        engine.dispose()
