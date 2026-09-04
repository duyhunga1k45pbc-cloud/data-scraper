import os
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import sessionmaker

from src.delivery.api import create_app
from src.storage.models import ScrapeRunRow

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRES") != "1",
    reason="set RUN_POSTGRES=1 to run PostgreSQL integration tests",
)


def test_m17_postgres_runs_delivery_is_read_only():
    engine = create_engine(os.environ["DATABASE_URL"], future=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    source = "m17_test_" + uuid.uuid4().hex
    at = datetime.now(timezone.utc)
    try:
        with factory() as session:
            with session.begin():
                session.add(
                    ScrapeRunRow(
                        source=source,
                        scope_key="default",
                        trigger_type="MANUAL",
                        started_at=at,
                        finished_at=at,
                        status="SUCCEEDED",
                        retry_of_run_id=None,
                        attempt=1,
                        accounting_complete=True,
                        records_seen=2,
                        records_created=1,
                        records_updated=1,
                        records_no_change=0,
                        records_stale=0,
                        records_rejected=0,
                        records_disappeared=0,
                        records_reappeared=0,
                        error_code=None,
                        error_message=None,
                    )
                )

        with factory() as session:
            before = session.scalar(
                select(func.count()).select_from(ScrapeRunRow).where(ScrapeRunRow.source == source)
            )

        with TestClient(create_app(session_factory=factory)) as client:
            response = client.get("/runs", params={"source": source})
            assert response.status_code == 200
            payload = response.json()
            assert payload["returned"] == 1
            assert payload["items"][0]["source"] == source
            assert payload["items"][0]["records_seen"] == 2

        with factory() as session:
            after = session.scalar(
                select(func.count()).select_from(ScrapeRunRow).where(ScrapeRunRow.source == source)
            )
        assert after == before == 1
    finally:
        with factory() as session:
            with session.begin():
                session.execute(delete(ScrapeRunRow).where(ScrapeRunRow.source == source))
        engine.dispose()
