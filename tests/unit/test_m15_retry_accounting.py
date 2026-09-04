from types import SimpleNamespace

from src.catalogs.models import CatalogRunStatus
from src.products.models import StateDecision
from src.runs.models import RunCounters
from src.storage.service import CatalogPersistenceResult


def _observed(decision: StateDecision):
    return SimpleNamespace(transition=SimpleNamespace(decision=decision))


def test_m15_retry_accounting_still_uses_explicit_result_envelope():
    result = CatalogPersistenceResult(
        catalog_run_id=91,
        coverage_status=CatalogRunStatus.COMPLETE,
        observed_results=(
            _observed(StateDecision.NO_CHANGE),
            _observed(StateDecision.STALE),
        ),
        absence_transitions=(SimpleNamespace(decision=StateDecision.DISAPPEARED),),
    )
    counters = RunCounters.from_catalog_result(result)
    assert counters.records_seen == 2
    assert counters.records_no_change == 1
    assert counters.records_stale == 1
    assert counters.records_disappeared == 1
