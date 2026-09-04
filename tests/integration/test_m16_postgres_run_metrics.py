import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from src.observability.metrics import collect_run_metrics
from src.storage.models import ScrapeRunRow

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES") != "1",
    reason="set RUN_POSTGRES=1 to run PostgreSQL integration tests",
)


def _run(source, *, status, started_at, finished_at, accounting_complete, **kw):
    values = dict(
        source=source,
        scope_key="default",
        trigger_type="SCHEDULED",
        started_at=started_at,
        finished_at=finished_at,
        status=status,
        retry_of_run_id=None,
        attempt=1,
        accounting_complete=accounting_complete,
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
    values.update(kw)
    return ScrapeRunRow(**values)


def test_m16_postgres_run_metrics_snapshot_respects_accounting_boundary():
    engine = create_engine(os.environ["DATABASE_URL"], future=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    source = "m16_test_" + uuid.uuid4().hex
    t0 = datetime.now(timezone.utc) - timedelta(minutes=5)

    try:
        with factory() as session:
            with session.begin():
                session.add_all(
                    [
                        _run(
                            source,
                            status="SUCCEEDED",
                            started_at=t0,
                            finished_at=t0 + timedelta(seconds=10),
                            accounting_complete=True,
                            records_seen=10,
                            records_created=2,
                            records_no_change=8,
                        ),
                        _run(
                            source,
                            status="FAILED",
                            started_at=t0 + timedelta(minutes=1),
                            finished_at=t0 + timedelta(minutes=1, seconds=3),
                            accounting_complete=True,
                            records_seen=4,
                            records_no_change=4,
                            error_code="CATALOG_INCOMPLETE",
                        ),
                        _run(
                            source,
                            status="FAILED",
                            started_at=t0 + timedelta(minutes=2),
                            finished_at=t0 + timedelta(minutes=3),
                            accounting_complete=False,
                            records_seen=999,
                            records_created=999,
                            error_code="RUN_ABANDONED",
                        ),
                    ]
                )

        snapshot = collect_run_metrics(factory, source=source, scope_key="default")
        assert snapshot.runs_total == 3
        assert snapshot.runs_succeeded == 1
        assert snapshot.runs_failed == 2
        assert snapshot.success_rate == pytest.approx(1 / 3)
        assert snapshot.accounting_incomplete == 1
        assert snapshot.abandoned_runs == 1
        assert snapshot.records_seen == 14
        assert snapshot.records_created == 2
        assert snapshot.failures_by_code == {
            "CATALOG_INCOMPLETE": 1,
            "RUN_ABANDONED": 1,
        }
    finally:
        with factory() as session:
            with session.begin():
                session.execute(delete(ScrapeRunRow).where(ScrapeRunRow.source == source))
        engine.dispose()
