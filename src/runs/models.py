from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.products.models import StateDecision
from src.storage.service import CatalogPersistenceResult


class ScrapeRunStatus(str, Enum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class ScrapeRunTrigger(str, Enum):
    MANUAL = "MANUAL"
    SCHEDULED = "SCHEDULED"


@dataclass(frozen=True)
class RunCounters:
    records_seen: int = 0
    records_created: int = 0
    records_updated: int = 0
    records_no_change: int = 0
    records_stale: int = 0
    records_rejected: int = 0
    records_disappeared: int = 0
    records_reappeared: int = 0

    @classmethod
    def from_catalog_result(cls, result: CatalogPersistenceResult) -> "RunCounters":
        decisions = [item.transition.decision for item in result.observed_results]
        absence_decisions = [item.decision for item in result.absence_transitions]
        return cls(
            records_seen=len(result.observed_results),
            records_created=decisions.count(StateDecision.CREATE),
            records_updated=decisions.count(StateDecision.UPDATE),
            records_no_change=decisions.count(StateDecision.NO_CHANGE),
            records_stale=decisions.count(StateDecision.STALE),
            records_rejected=decisions.count(StateDecision.REJECT),
            records_disappeared=absence_decisions.count(StateDecision.DISAPPEARED),
            records_reappeared=decisions.count(StateDecision.REAPPEARED),
        )


@dataclass(frozen=True)
class ScrapeRunResult:
    run_id: int
    status: ScrapeRunStatus
    counters: RunCounters
    catalog_result: CatalogPersistenceResult | None
    error_code: str | None = None
    error_message: str | None = None
