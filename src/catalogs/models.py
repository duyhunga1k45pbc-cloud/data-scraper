from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from src.acquisition.models import RawEvidence
from src.products.models import ProductObservation


class CatalogRunStatus(str, Enum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class CatalogChunkStatus(str, Enum):
    SUCCESS = "SUCCESS"
    HTTP_ERROR = "HTTP_ERROR"
    FETCH_FAILED = "FETCH_FAILED"
    PARSE_FAILED = "PARSE_FAILED"
    LIMIT_REACHED = "LIMIT_REACHED"
    CYCLE_DETECTED = "CYCLE_DETECTED"
    LEGACY_INCOMPLETE = "LEGACY_INCOMPLETE"


@dataclass(frozen=True)
class CatalogPage:
    observations: tuple[ProductObservation, ...]
    next_ref: str | None


@dataclass(frozen=True)
class CatalogChunkResult:
    sequence: int
    requested_ref: str
    attempted_at: datetime
    status: CatalogChunkStatus
    evidence: RawEvidence | None = None
    observations: tuple[ProductObservation, ...] = ()
    next_ref: str | None = None
    error_code: str | None = None

    @property
    def record_count(self) -> int:
        return len(self.observations)


@dataclass(frozen=True)
class CatalogAcquisition:
    """Evidence-backed acquisition of one configured catalog scope.

    Completeness is derived from the acquired chunk chain. Callers do not set a
    COMPLETE boolean. A run is COMPLETE only when acquisition starts at the
    configured start reference, every traversed chunk succeeds, each next_ref
    leads to the following requested_ref, and the final successful chunk proves
    the terminal condition with next_ref=None.
    """

    run_key: str
    source: str
    scope_key: str
    start_ref: str
    chunks: tuple[CatalogChunkResult, ...]

    @property
    def coverage_status(self) -> CatalogRunStatus:
        if not self.chunks:
            return CatalogRunStatus.INCOMPLETE

        expected_ref: str | None = self.start_ref
        for expected_sequence, chunk in enumerate(self.chunks):
            if chunk.sequence != expected_sequence:
                return CatalogRunStatus.INCOMPLETE
            if expected_ref is None or chunk.requested_ref != expected_ref:
                return CatalogRunStatus.INCOMPLETE
            if chunk.status != CatalogChunkStatus.SUCCESS:
                return CatalogRunStatus.INCOMPLETE
            expected_ref = chunk.next_ref

        return (
            CatalogRunStatus.COMPLETE
            if expected_ref is None
            else CatalogRunStatus.INCOMPLETE
        )

    @property
    def terminal_reached(self) -> bool:
        return self.coverage_status == CatalogRunStatus.COMPLETE

    @property
    def observations(self) -> tuple[ProductObservation, ...]:
        return tuple(
            observation
            for chunk in self.chunks
            if chunk.status == CatalogChunkStatus.SUCCESS
            for observation in chunk.observations
        )

    @property
    def evidence(self) -> tuple[RawEvidence, ...]:
        return tuple(
            chunk.evidence
            for chunk in self.chunks
            if chunk.evidence is not None
        )

    @property
    def observed_at(self) -> datetime:
        if not self.chunks:
            raise ValueError("catalog acquisition requires at least one chunk attempt")
        values = [chunk.attempted_at for chunk in self.chunks]
        values.extend(item.fetched_at for item in self.evidence)
        normalized = [
            value.replace(tzinfo=timezone.utc)
            if value.tzinfo is None
            else value.astimezone(timezone.utc)
            for value in values
        ]
        return max(normalized)
