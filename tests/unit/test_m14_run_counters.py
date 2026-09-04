from types import SimpleNamespace

from src.catalogs.models import CatalogRunStatus
from src.products.models import StateDecision
from src.runs.models import RunCounters
from src.storage.service import CatalogPersistenceResult


def _observed(decision: StateDecision):
    return SimpleNamespace(transition=SimpleNamespace(decision=decision))


def _absence(decision: StateDecision):
    return SimpleNamespace(decision=decision)


def test_m14_counters_include_direct_and_absence_transitions():
    result = CatalogPersistenceResult(
        catalog_run_id=9,
        coverage_status=CatalogRunStatus.COMPLETE,
        observed_results=(
            _observed(StateDecision.CREATE),
            _observed(StateDecision.UPDATE),
            _observed(StateDecision.NO_CHANGE),
            _observed(StateDecision.STALE),
            _observed(StateDecision.REJECT),
            _observed(StateDecision.REAPPEARED),
        ),
        absence_transitions=(
            _absence(StateDecision.DISAPPEARED),
            _absence(StateDecision.NO_CHANGE),
        ),
    )

    counters = RunCounters.from_catalog_result(result)

    assert counters.records_seen == 6
    assert counters.records_created == 1
    assert counters.records_updated == 1
    assert counters.records_no_change == 1
    assert counters.records_stale == 1
    assert counters.records_rejected == 1
    assert counters.records_reappeared == 1
    assert counters.records_disappeared == 1
