from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalogs.models import CatalogRunStatus
from src.products.models import StateDecision
from src.runs.service import execute_catalog_operation
from src.storage.models import Base
from src.storage.service import CatalogPersistenceResult


def test_m16_run_lifecycle_emits_started_and_finished_without_changing_result(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    events = []

    def capture(event, **fields):
        events.append((event, fields))
        return True

    monkeypatch.setattr("src.runs.service.emit_event", capture)
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

    run = execute_catalog_operation(
        factory,
        source="m16-source",
        scope_key="default",
        operation=lambda: result,
    )

    assert run.status.value == "SUCCEEDED"
    assert run.counters.records_seen == 1
    assert [name for name, _ in events] == [
        "scrape_run_started",
        "scrape_run_finished",
    ]
    assert events[0][1]["run_id"] == run.run_id
    assert events[1][1]["run_id"] == run.run_id
    assert events[1][1]["records_seen"] == 1
    assert "error_message" not in events[1][1]
    engine.dispose()
