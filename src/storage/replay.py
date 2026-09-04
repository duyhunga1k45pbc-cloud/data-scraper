from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.catalogs.models import CatalogChunkStatus, CatalogRunStatus
from src.products.models import ProductPresenceStatus, StateDecision

from .models import (
    CatalogRunChunkRow,
    CatalogRunRow,
    ProductHistoryRow,
    ProductObservationRow,
    ProductRow,
    RawEvidenceRow,
)
from .repositories import row_to_current_state


_ACCEPTED_DIRECT_DECISIONS = {
    StateDecision.CREATE.value,
    StateDecision.UPDATE.value,
    StateDecision.REAPPEARED.value,
}
_HISTORY_DECISIONS = _ACCEPTED_DIRECT_DECISIONS | {StateDecision.DISAPPEARED.value}


@dataclass(frozen=True)
class ReplayIssue:
    code: str
    message: str
    identity_key: str | None = None
    history_id: int | None = None


@dataclass(frozen=True)
class ReplayedProduct:
    source: str
    identity_key: str
    product_id: int
    expected_state: dict[str, Any]
    actual_state: dict[str, Any]
    expected_accepted_observation_id: int | None
    actual_accepted_observation_id: int
    history_ids: tuple[int, ...]

    @property
    def matches_current_projection(self) -> bool:
        return (
            self.expected_state == self.actual_state
            and self.expected_accepted_observation_id
            == self.actual_accepted_observation_id
        )


@dataclass(frozen=True)
class ReplayReport:
    source: str
    products: tuple[ReplayedProduct, ...]
    issues: tuple[ReplayIssue, ...]

    @property
    def is_consistent(self) -> bool:
        return not self.issues and all(
            item.matches_current_projection for item in self.products
        )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return _as_utc(value)
    parsed = datetime.fromisoformat(value)
    return _as_utc(parsed)


def _canonical_datetime(value: str | datetime) -> str:
    return _parse_datetime(value).isoformat()


def _canonical_decimal(value: Any) -> Any:
    """Normalize numeric representation without changing its semantic value.

    PostgreSQL ``NUMERIC(18, 2)`` materializes ``199.0`` as ``199.00`` while
    history JSON preserves the original Decimal string. Replay compares meaning,
    not scale/presentation, so both must canonicalize to the same representation.
    """

    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return value
    if not number.is_finite():
        return str(number)
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def _canonical_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Normalize historical snapshot schemas to the current projection shape.

    M2/M3/M8 migrations backfilled relational columns but deliberately did not
    rewrite older JSON history snapshots. Replay must therefore apply those same
    deterministic defaults instead of treating schema evolution as corruption.
    """

    value = deepcopy(snapshot)

    value.setdefault("source_record_id", None)
    value.setdefault("canonical_product_url", None)
    if value.get("identity_key") is None:
        if value.get("source_record_id"):
            value["identity_key"] = f"id:{value['source_record_id']}"
        elif value.get("canonical_product_url"):
            value["identity_key"] = f"url:{value['canonical_product_url']}"

    value.setdefault("compare_at_price", None)
    value["price"] = _canonical_decimal(value.get("price"))
    value["compare_at_price"] = _canonical_decimal(value.get("compare_at_price"))

    value.setdefault("sku", None)
    if "categories" not in value:
        category = value.get("category")
        value["categories"] = [category] if category is not None else []
    value.setdefault("variants", [])
    for variant in value["variants"]:
        if isinstance(variant, dict):
            variant["price"] = _canonical_decimal(variant.get("price"))

    value.setdefault("presence_status", ProductPresenceStatus.ACTIVE.value)
    if value.get("presence_observed_at") is None and value.get("observed_at") is not None:
        value["presence_observed_at"] = value["observed_at"]

    for key in ("observed_at", "updated_at", "presence_observed_at"):
        if value.get(key) is not None:
            value[key] = _canonical_datetime(value[key])
    return value


def _actual_snapshot(row: ProductRow) -> dict[str, Any]:
    state = row_to_current_state(row)
    return _canonical_snapshot(
        {
            "source": state.identity.source,
            "identity_key": state.identity.key,
            "source_record_id": state.identity.source_record_id,
            "canonical_product_url": state.identity.canonical_product_url,
            "title": state.title,
            "price": str(state.price),
            "compare_at_price": (
                str(state.compare_at_price)
                if state.compare_at_price is not None
                else None
            ),
            "currency": state.currency.value,
            "availability": state.availability.value,
            "quantity": state.quantity,
            "category": state.category,
            "sku": state.sku,
            "categories": list(state.categories),
            "variants": [
                {
                    "key": item.key,
                    "sku": item.sku,
                    "options": [list(pair) for pair in item.options],
                    "price": str(item.price),
                    "availability": item.availability.value,
                }
                for item in state.variants
            ],
            "source_url": state.source_url,
            "observed_at": state.observed_at,
            "updated_at": state.updated_at,
            "presence_status": state.presence_status.value,
            "presence_observed_at": (
                state.presence_observed_at or state.observed_at
            ),
        }
    )


def _continuity_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """State fields that must chain across accepted history entries.

    ``presence_observed_at`` may legitimately advance on a NO_CHANGE direct
    observation or a repeated complete absence without a history row. Every
    other current-state field remains part of accepted-history continuity.
    """

    value = _canonical_snapshot(snapshot)
    value.pop("presence_observed_at", None)
    return value


def _verify_raw_evidence(
    evidence: RawEvidenceRow | None,
    *,
    issues: list[ReplayIssue],
    identity_key: str | None,
    history_id: int | None,
    context: str,
) -> None:
    if evidence is None:
        issues.append(
            ReplayIssue(
                code="MISSING_RAW_EVIDENCE",
                message=f"{context} has no RawEvidence row",
                identity_key=identity_key,
                history_id=history_id,
            )
        )
        return

    actual_hash = sha256(evidence.body.encode("utf-8")).hexdigest()
    if actual_hash != evidence.body_hash:
        issues.append(
            ReplayIssue(
                code="RAW_EVIDENCE_HASH_MISMATCH",
                message=f"{context} RawEvidence body no longer matches body_hash",
                identity_key=identity_key,
                history_id=history_id,
            )
        )


def _persisted_catalog_coverage_status(
    run: CatalogRunRow,
    chunks: list[CatalogRunChunkRow],
) -> CatalogRunStatus:
    if not chunks:
        return CatalogRunStatus.INCOMPLETE

    expected_ref: str | None = run.start_ref
    for expected_sequence, chunk in enumerate(chunks):
        if chunk.sequence != expected_sequence:
            return CatalogRunStatus.INCOMPLETE
        if expected_ref is None or chunk.requested_ref != expected_ref:
            return CatalogRunStatus.INCOMPLETE
        if chunk.status != CatalogChunkStatus.SUCCESS.value:
            return CatalogRunStatus.INCOMPLETE
        expected_ref = chunk.next_ref

    return (
        CatalogRunStatus.COMPLETE
        if expected_ref is None
        else CatalogRunStatus.INCOMPLETE
    )


def _catalog_run_seen_identity_keys(
    session: Session,
    run: CatalogRunRow,
) -> set[str]:
    evidence_ids = list(
        session.scalars(
            select(CatalogRunChunkRow.evidence_id).where(
                CatalogRunChunkRow.catalog_run_id == run.id,
                CatalogRunChunkRow.evidence_id.is_not(None),
            )
        )
    )
    if not evidence_ids:
        return set()

    return set(
        session.scalars(
            select(ProductObservationRow.identity_key).where(
                ProductObservationRow.source == run.source,
                ProductObservationRow.evidence_id.in_(evidence_ids),
            )
        )
    )


def _verify_catalog_run(
    session: Session,
    run: CatalogRunRow | None,
    *,
    issues: list[ReplayIssue],
    identity_key: str,
    history_id: int | None,
) -> None:
    if run is None:
        issues.append(
            ReplayIssue(
                code="MISSING_CATALOG_RUN",
                message="catalog-backed replay evidence has no catalog run",
                identity_key=identity_key,
                history_id=history_id,
            )
        )
        return

    chunks = list(
        session.scalars(
            select(CatalogRunChunkRow)
            .where(CatalogRunChunkRow.catalog_run_id == run.id)
            .order_by(CatalogRunChunkRow.sequence)
        )
    )
    derived = _persisted_catalog_coverage_status(run, chunks)
    if run.status != derived.value or derived != CatalogRunStatus.COMPLETE:
        issues.append(
            ReplayIssue(
                code="INVALID_DISAPPEARANCE_COVERAGE_PROOF",
                message=(
                    f"catalog run {run.run_key!r} is stored as {run.status!r} "
                    f"but persisted chunks derive {derived.value!r}"
                ),
                identity_key=identity_key,
                history_id=history_id,
            )
        )

    if sum(chunk.record_count for chunk in chunks) != run.record_count:
        issues.append(
            ReplayIssue(
                code="CATALOG_RECORD_COUNT_MISMATCH",
                message=f"catalog run {run.run_key!r} record_count does not match chunks",
                identity_key=identity_key,
                history_id=history_id,
            )
        )

    for chunk in chunks:
        if chunk.evidence_id is None:
            if chunk.status == CatalogChunkStatus.SUCCESS.value:
                issues.append(
                    ReplayIssue(
                        code="SUCCESS_CHUNK_WITHOUT_EVIDENCE",
                        message=(
                            f"catalog run {run.run_key!r} success chunk "
                            f"{chunk.sequence} has no RawEvidence"
                        ),
                        identity_key=identity_key,
                        history_id=history_id,
                    )
                )
            continue
        evidence = session.get(RawEvidenceRow, chunk.evidence_id)
        _verify_raw_evidence(
            evidence,
            issues=issues,
            identity_key=identity_key,
            history_id=history_id,
            context=f"catalog run {run.run_key!r} chunk {chunk.sequence}",
        )


def _verify_observation_provenance(
    session: Session,
    history: ProductHistoryRow,
    *,
    expected_source: str,
    expected_identity_key: str,
    issues: list[ReplayIssue],
) -> None:
    if history.observation_id is None:
        issues.append(
            ReplayIssue(
                code="MISSING_OBSERVATION_PROVENANCE",
                message=f"{history.decision} history requires an observation",
                identity_key=expected_identity_key,
                history_id=history.id,
            )
        )
        return

    observation = session.get(ProductObservationRow, history.observation_id)
    if observation is None:
        issues.append(
            ReplayIssue(
                code="MISSING_OBSERVATION",
                message="history observation_id does not exist",
                identity_key=expected_identity_key,
                history_id=history.id,
            )
        )
        return

    if observation.source != expected_source or observation.identity_key != expected_identity_key:
        issues.append(
            ReplayIssue(
                code="OBSERVATION_IDENTITY_MISMATCH",
                message="history observation does not belong to the replayed product identity",
                identity_key=expected_identity_key,
                history_id=history.id,
            )
        )

    if observation.state_decision != history.decision:
        issues.append(
            ReplayIssue(
                code="OBSERVATION_DECISION_MISMATCH",
                message=(
                    f"observation stores {observation.state_decision!r} but history "
                    f"stores {history.decision!r}"
                ),
                identity_key=expected_identity_key,
                history_id=history.id,
            )
        )

    evidence = session.get(RawEvidenceRow, observation.evidence_id)
    _verify_raw_evidence(
        evidence,
        issues=issues,
        identity_key=expected_identity_key,
        history_id=history.id,
        context=f"observation {observation.id}",
    )


def _refresh_presence_from_no_history_evidence(
    session: Session,
    *,
    source: str,
    identity_key: str,
    snapshot: dict[str, Any],
    issues: list[ReplayIssue],
) -> dict[str, Any]:
    replayed = _canonical_snapshot(snapshot)
    presence_time = _parse_datetime(replayed["presence_observed_at"])
    presence_status = replayed["presence_status"]

    # Direct NO_CHANGE observations are accepted evidence that the product was
    # present, even though they intentionally create no business history row.
    no_change_observations = list(
        session.scalars(
            select(ProductObservationRow)
            .where(
                ProductObservationRow.source == source,
                ProductObservationRow.identity_key == identity_key,
                ProductObservationRow.state_decision == StateDecision.NO_CHANGE.value,
            )
            .order_by(ProductObservationRow.id)
        )
    )
    for observation in no_change_observations:
        _verify_raw_evidence(
            session.get(RawEvidenceRow, observation.evidence_id),
            issues=issues,
            identity_key=identity_key,
            history_id=None,
            context=f"NO_CHANGE observation {observation.id}",
        )
        observed_at = _as_utc(observation.observed_at)
        if observed_at <= presence_time:
            continue
        if presence_status != ProductPresenceStatus.ACTIVE.value:
            issues.append(
                ReplayIssue(
                    code="UNEXPLAINED_ACTIVE_FRESHNESS_AFTER_DISAPPEARANCE",
                    message=(
                        "a newer NO_CHANGE observation exists after the final "
                        "DISAPPEARED history; a REAPPEARED transition would be expected"
                    ),
                    identity_key=identity_key,
                )
            )
            continue
        presence_time = observed_at
        replayed["presence_observed_at"] = observed_at.isoformat()

    # Repeated complete absence while already DISAPPEARED refreshes presence
    # freshness but deliberately creates no duplicate DISAPPEARED history.
    complete_runs = list(
        session.scalars(
            select(CatalogRunRow)
            .where(
                CatalogRunRow.source == source,
                CatalogRunRow.status == CatalogRunStatus.COMPLETE.value,
            )
            .order_by(CatalogRunRow.observed_at, CatalogRunRow.id)
        )
    )
    for run in complete_runs:
        observed_at = _as_utc(run.observed_at)
        if observed_at <= presence_time:
            continue
        seen = _catalog_run_seen_identity_keys(session, run)
        if identity_key in seen:
            continue

        chunks = list(
            session.scalars(
                select(CatalogRunChunkRow)
                .where(CatalogRunChunkRow.catalog_run_id == run.id)
                .order_by(CatalogRunChunkRow.sequence)
            )
        )
        if _persisted_catalog_coverage_status(run, chunks) != CatalogRunStatus.COMPLETE:
            continue

        _verify_catalog_run(
            session,
            run,
            issues=issues,
            identity_key=identity_key,
            history_id=None,
        )

        if presence_status != ProductPresenceStatus.DISAPPEARED.value:
            issues.append(
                ReplayIssue(
                    code="MISSING_DISAPPEARED_HISTORY",
                    message=(
                        f"complete catalog run {run.run_key!r} is newer than active "
                        "presence and omits the identity, but no DISAPPEARED history "
                        "is reflected in the final projection"
                    ),
                    identity_key=identity_key,
                )
            )
            continue

        presence_time = observed_at
        replayed["presence_observed_at"] = observed_at.isoformat()

    return replayed


def replay_source_projection(session: Session, *, source: str) -> ReplayReport:
    """Rebuild and verify one source's trusted projection from persisted semantics.

    M10 intentionally replays the *persisted semantic ledger*: accepted
    ``product_history`` snapshots plus no-history presence freshness evidence,
    while verifying every accepted transition's provenance back to RawEvidence
    or an evidence-backed COMPLETE catalog proof.

    This does not re-run source parser code against raw bodies. Historical raw
    re-extraction would require an immutable/version-addressable extractor
    runtime, which the project does not yet persist.
    """

    issues: list[ReplayIssue] = []
    products: list[ReplayedProduct] = []

    rows = list(
        session.scalars(
            select(ProductRow)
            .where(ProductRow.source == source)
            .order_by(ProductRow.identity_key)
        )
    )
    current_identity_keys = {row.identity_key for row in rows}
    ledger_identity_keys = set(
        session.scalars(
            select(ProductHistoryRow.identity_key).where(
                ProductHistoryRow.source == source
            )
        )
    )
    for identity_key in sorted(ledger_identity_keys - current_identity_keys):
        issues.append(
            ReplayIssue(
                code="MISSING_CURRENT_PROJECTION",
                message="accepted semantic ledger has no current products row",
                identity_key=identity_key,
            )
        )

    for row in rows:
        histories = list(
            session.scalars(
                select(ProductHistoryRow)
                .where(
                    ProductHistoryRow.source == source,
                    ProductHistoryRow.identity_key == row.identity_key,
                )
                .order_by(ProductHistoryRow.id)
            )
        )
        if not histories:
            issues.append(
                ReplayIssue(
                    code="PRODUCT_WITHOUT_HISTORY",
                    message="current product has no accepted history to replay",
                    identity_key=row.identity_key,
                )
            )
            continue

        previous_new_state: dict[str, Any] | None = None
        expected_accepted_observation_id: int | None = None
        final_state: dict[str, Any] | None = None

        for index, history in enumerate(histories):
            if history.decision not in _HISTORY_DECISIONS:
                issues.append(
                    ReplayIssue(
                        code="UNEXPECTED_HISTORY_DECISION",
                        message=f"history contains non-accepted decision {history.decision!r}",
                        identity_key=row.identity_key,
                        history_id=history.id,
                    )
                )

            new_state = _canonical_snapshot(history.new_state)
            if new_state.get("source") != source or new_state.get("identity_key") != row.identity_key:
                issues.append(
                    ReplayIssue(
                        code="HISTORY_IDENTITY_MISMATCH",
                        message="history snapshot identity differs from current product identity",
                        identity_key=row.identity_key,
                        history_id=history.id,
                    )
                )

            if index == 0:
                if history.decision != StateDecision.CREATE.value or history.previous_state is not None:
                    issues.append(
                        ReplayIssue(
                            code="INVALID_HISTORY_START",
                            message="replay history must start with CREATE and previous_state=null",
                            identity_key=row.identity_key,
                            history_id=history.id,
                        )
                    )
            else:
                if history.previous_state is None:
                    issues.append(
                        ReplayIssue(
                            code="MISSING_PREVIOUS_STATE",
                            message="non-CREATE history must include previous_state",
                            identity_key=row.identity_key,
                            history_id=history.id,
                        )
                    )
                elif previous_new_state is not None and (
                    _continuity_snapshot(history.previous_state)
                    != _continuity_snapshot(previous_new_state)
                ):
                    issues.append(
                        ReplayIssue(
                            code="HISTORY_CHAIN_DIVERGENCE",
                            message=(
                                "history previous_state does not continue the preceding "
                                "accepted new_state"
                            ),
                            identity_key=row.identity_key,
                            history_id=history.id,
                        )
                    )

            if history.decision in _ACCEPTED_DIRECT_DECISIONS:
                _verify_observation_provenance(
                    session,
                    history,
                    expected_source=source,
                    expected_identity_key=row.identity_key,
                    issues=issues,
                )
                if history.observation_id is not None:
                    expected_accepted_observation_id = history.observation_id
            elif history.decision == StateDecision.DISAPPEARED.value:
                if history.observation_id is not None or history.catalog_run_id is None:
                    issues.append(
                        ReplayIssue(
                            code="INVALID_DISAPPEARANCE_PROVENANCE",
                            message="DISAPPEARED must use catalog_run_id only",
                            identity_key=row.identity_key,
                            history_id=history.id,
                        )
                    )
                _verify_catalog_run(
                    session,
                    session.get(CatalogRunRow, history.catalog_run_id)
                    if history.catalog_run_id is not None
                    else None,
                    issues=issues,
                    identity_key=row.identity_key,
                    history_id=history.id,
                )

            previous_new_state = new_state
            final_state = new_state

        assert final_state is not None
        final_state = _refresh_presence_from_no_history_evidence(
            session,
            source=source,
            identity_key=row.identity_key,
            snapshot=final_state,
            issues=issues,
        )
        actual_state = _actual_snapshot(row)

        replayed = ReplayedProduct(
            source=source,
            identity_key=row.identity_key,
            product_id=row.id,
            expected_state=final_state,
            actual_state=actual_state,
            expected_accepted_observation_id=expected_accepted_observation_id,
            actual_accepted_observation_id=row.accepted_observation_id,
            history_ids=tuple(history.id for history in histories),
        )
        products.append(replayed)

        if final_state != actual_state:
            differing_fields = sorted(
                key
                for key in set(final_state) | set(actual_state)
                if final_state.get(key) != actual_state.get(key)
            )
            issues.append(
                ReplayIssue(
                    code="CURRENT_PROJECTION_MISMATCH",
                    message=(
                        "current products row differs from replayed trusted state"
                        + (f"; fields={','.join(differing_fields)}" if differing_fields else "")
                    ),
                    identity_key=row.identity_key,
                )
            )
        if expected_accepted_observation_id != row.accepted_observation_id:
            issues.append(
                ReplayIssue(
                    code="ACCEPTED_OBSERVATION_MISMATCH",
                    message=(
                        "current accepted_observation_id differs from the latest "
                        "accepted direct history provenance"
                    ),
                    identity_key=row.identity_key,
                )
            )

    return ReplayReport(
        source=source,
        products=tuple(products),
        issues=tuple(issues),
    )
