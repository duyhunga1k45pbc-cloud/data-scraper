from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from src.products.models import StateDecision

from .models import ProductHistoryRow, ProductRow
from .reextraction import ReextractionReport, verify_source_reextraction
from .replay import (
    ReplayIssue,
    _canonical_snapshot,
    _continuity_snapshot,
    _parse_datetime,
    _refresh_presence_from_no_history_evidence,
    _verify_catalog_run,
    _verify_observation_provenance,
)
from .models import CatalogRunRow


_ACCEPTED_DIRECT_DECISIONS = {
    StateDecision.CREATE.value,
    StateDecision.UPDATE.value,
    StateDecision.REAPPEARED.value,
}
_HISTORY_DECISIONS = _ACCEPTED_DIRECT_DECISIONS | {StateDecision.DISAPPEARED.value}


@dataclass(frozen=True)
class LedgerProjectionProduct:
    source: str
    identity_key: str
    expected_state: dict[str, Any]
    accepted_observation_id: int
    history_ids: tuple[int, ...]


@dataclass(frozen=True)
class LedgerProjection:
    source: str
    products: tuple[LedgerProjectionProduct, ...]
    issues: tuple[ReplayIssue, ...]

    @property
    def is_consistent(self) -> bool:
        return not self.issues


@dataclass(frozen=True)
class ProjectionRebuildIssue:
    code: str
    message: str
    identity_key: str | None = None
    history_id: int | None = None


@dataclass(frozen=True)
class RebuiltProjectionProduct:
    source: str
    identity_key: str
    old_product_id: int | None
    new_product_id: int
    accepted_observation_id: int
    state: dict[str, Any]


@dataclass(frozen=True)
class ProjectionRebuildReport:
    source: str
    products: tuple[RebuiltProjectionProduct, ...]
    history_rows: int
    extraction: ReextractionReport
    issues: tuple[ProjectionRebuildIssue, ...]

    @property
    def is_consistent(self) -> bool:
        return self.extraction.is_consistent and not self.issues


def _history_identity_matches_snapshot(
    history: ProductHistoryRow,
    snapshot: dict[str, Any],
) -> bool:
    return (
        snapshot.get("source") == history.source
        and snapshot.get("identity_key") == history.identity_key
    )


def build_source_projection_from_ledger(
    session: Session,
    *,
    source: str,
) -> LedgerProjection:
    """Build one source projection without reading the products table.

    M12 treats product_history as the stable semantic ledger. Histories are
    discovered by persisted `(source, identity_key)` rather than the mutable
    projection's surrogate `product_id`. The function starts from an empty
    in-memory projection, applies accepted history continuity, then advances
    presence freshness from no-history evidence exactly as M10 does.
    """

    issues: list[ReplayIssue] = []
    histories = list(
        session.scalars(
            select(ProductHistoryRow)
            .where(ProductHistoryRow.source == source)
            .order_by(ProductHistoryRow.identity_key, ProductHistoryRow.id)
        )
    )
    grouped: dict[str, list[ProductHistoryRow]] = defaultdict(list)
    for history in histories:
        grouped[history.identity_key].append(history)

    products: list[LedgerProjectionProduct] = []
    for identity_key in sorted(grouped):
        rows = grouped[identity_key]
        previous_new_state: dict[str, Any] | None = None
        accepted_observation_id: int | None = None
        final_state: dict[str, Any] | None = None

        for index, history in enumerate(rows):
            if history.decision not in _HISTORY_DECISIONS:
                issues.append(
                    ReplayIssue(
                        code="UNEXPECTED_HISTORY_DECISION",
                        message=f"history contains non-accepted decision {history.decision!r}",
                        identity_key=identity_key,
                        history_id=history.id,
                    )
                )

            new_state = _canonical_snapshot(history.new_state)
            if not _history_identity_matches_snapshot(history, new_state):
                issues.append(
                    ReplayIssue(
                        code="HISTORY_IDENTITY_MISMATCH",
                        message=(
                            "history stable identity columns differ from its new_state "
                            "snapshot identity"
                        ),
                        identity_key=identity_key,
                        history_id=history.id,
                    )
                )

            if index == 0:
                if history.decision != StateDecision.CREATE.value or history.previous_state is not None:
                    issues.append(
                        ReplayIssue(
                            code="INVALID_HISTORY_START",
                            message="rebuild history must start with CREATE and previous_state=null",
                            identity_key=identity_key,
                            history_id=history.id,
                        )
                    )
            else:
                if history.previous_state is None:
                    issues.append(
                        ReplayIssue(
                            code="MISSING_PREVIOUS_STATE",
                            message="non-CREATE history must include previous_state",
                            identity_key=identity_key,
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
                            identity_key=identity_key,
                            history_id=history.id,
                        )
                    )

            if history.decision in _ACCEPTED_DIRECT_DECISIONS:
                _verify_observation_provenance(
                    session,
                    history,
                    expected_source=source,
                    expected_identity_key=identity_key,
                    issues=issues,
                )
                if history.observation_id is not None:
                    accepted_observation_id = history.observation_id
            elif history.decision == StateDecision.DISAPPEARED.value:
                if history.observation_id is not None or history.catalog_run_id is None:
                    issues.append(
                        ReplayIssue(
                            code="INVALID_DISAPPEARANCE_PROVENANCE",
                            message="DISAPPEARED must use catalog_run_id only",
                            identity_key=identity_key,
                            history_id=history.id,
                        )
                    )
                _verify_catalog_run(
                    session,
                    session.get(CatalogRunRow, history.catalog_run_id)
                    if history.catalog_run_id is not None
                    else None,
                    issues=issues,
                    identity_key=identity_key,
                    history_id=history.id,
                )

            previous_new_state = new_state
            final_state = new_state

        if final_state is None:
            continue
        if accepted_observation_id is None:
            issues.append(
                ReplayIssue(
                    code="MISSING_ACCEPTED_OBSERVATION",
                    message=(
                        "ledger identity has no accepted direct observation to anchor "
                        "products.accepted_observation_id"
                    ),
                    identity_key=identity_key,
                )
            )
            continue

        final_state = _refresh_presence_from_no_history_evidence(
            session,
            source=source,
            identity_key=identity_key,
            snapshot=final_state,
            issues=issues,
        )
        products.append(
            LedgerProjectionProduct(
                source=source,
                identity_key=identity_key,
                expected_state=final_state,
                accepted_observation_id=accepted_observation_id,
                history_ids=tuple(item.id for item in rows),
            )
        )

    return LedgerProjection(
        source=source,
        products=tuple(products),
        issues=tuple(issues),
    )


def _product_snapshot(row: ProductRow) -> dict[str, Any]:
    return _canonical_snapshot(
        {
            "source": row.source,
            "identity_key": row.identity_key,
            "source_record_id": row.source_record_id,
            "canonical_product_url": row.canonical_product_url,
            "title": row.title,
            "price": str(row.price),
            "compare_at_price": (
                str(row.compare_at_price) if row.compare_at_price is not None else None
            ),
            "currency": row.currency,
            "availability": row.availability,
            "quantity": row.quantity,
            "category": row.category,
            "sku": row.sku,
            "categories": list(row.categories or []),
            "variants": list(row.variants or []),
            "source_url": row.source_url,
            "observed_at": row.observed_at,
            "updated_at": row.updated_at,
            "presence_status": row.presence_status,
            "presence_observed_at": row.presence_observed_at,
        }
    )


def _insert_projection_row(
    session: Session,
    *,
    product: LedgerProjectionProduct,
    product_id: int | None = None,
) -> ProductRow:
    state = product.expected_state
    row = ProductRow(
        id=product_id,
        source=product.source,
        identity_key=product.identity_key,
        source_record_id=state.get("source_record_id"),
        canonical_product_url=state.get("canonical_product_url"),
        title=str(state["title"]),
        price=Decimal(str(state["price"])),
        compare_at_price=(
            Decimal(str(state["compare_at_price"]))
            if state.get("compare_at_price") is not None
            else None
        ),
        currency=str(state["currency"]),
        availability=str(state["availability"]),
        quantity=state.get("quantity"),
        category=state.get("category"),
        sku=state.get("sku"),
        categories=list(state.get("categories") or []),
        variants=list(state.get("variants") or []),
        source_url=str(state["source_url"]),
        observed_at=_parse_datetime(state["observed_at"]),
        updated_at=_parse_datetime(state["updated_at"]),
        presence_status=str(state["presence_status"]),
        presence_observed_at=_parse_datetime(state["presence_observed_at"]),
        accepted_observation_id=product.accepted_observation_id,
    )
    session.add(row)
    session.flush()
    return row


def _copy_replay_issues(issues: tuple[ReplayIssue, ...]) -> list[ProjectionRebuildIssue]:
    return [
        ProjectionRebuildIssue(
            code=item.code,
            message=item.message,
            identity_key=item.identity_key,
            history_id=item.history_id,
        )
        for item in issues
    ]


def rebuild_source_projection_in_place(
    session: Session,
    *,
    source: str,
) -> ProjectionRebuildReport:
    """Replace one source's products projection from the independent ledger.

    The function can recover from an empty or drifted `products` projection. It
    reads RawEvidence/ProductObservation/catalog proof/product_history, but the
    expected state is derived without reading ProductRow. The caller owns the
    transaction and decides whether to commit. `verify-rebuild` runs this exact
    operation and always rolls it back.
    """

    extraction = verify_source_reextraction(session, source=source)
    ledger = build_source_projection_from_ledger(session, source=source)
    issues = _copy_replay_issues(ledger.issues)
    for item in extraction.issues:
        issues.append(
            ProjectionRebuildIssue(
                code=f"EXTRACTION_{item.code}",
                message=item.message,
                identity_key=item.identity_key,
            )
        )

    expected = {item.identity_key: item for item in ledger.products}
    current_rows = list(
        session.scalars(
            select(ProductRow)
            .where(ProductRow.source == source)
            .order_by(ProductRow.identity_key)
        )
    )
    old_ids = {row.identity_key: row.id for row in current_rows}

    # Fail closed before touching the mutable projection when the independent
    # evidence/ledger chain cannot justify a deterministic rebuild.
    if issues:
        return ProjectionRebuildReport(
            source=source,
            products=(),
            history_rows=len(
                list(
                    session.scalars(
                        select(ProductHistoryRow.id).where(ProductHistoryRow.source == source)
                    )
                )
            ),
            extraction=extraction,
            issues=tuple(issues),
        )

    # Detach the semantic ledger from mutable projection ids before deleting any
    # projection rows. This works even when products is already empty.
    session.execute(
        update(ProductHistoryRow)
        .where(ProductHistoryRow.source == source)
        .values(product_id=None)
    )
    session.flush()
    session.execute(delete(ProductRow).where(ProductRow.source == source))
    session.flush()

    rebuilt: list[RebuiltProjectionProduct] = []
    for identity_key in sorted(expected):
        product = expected[identity_key]
        row = _insert_projection_row(
            session,
            product=product,
            product_id=old_ids.get(identity_key),
        )
        session.execute(
            update(ProductHistoryRow)
            .where(
                ProductHistoryRow.source == source,
                ProductHistoryRow.identity_key == identity_key,
            )
            .values(product_id=row.id)
        )
        session.flush()

        actual = _product_snapshot(row)
        if actual != product.expected_state:
            fields = sorted(
                key
                for key in set(actual) | set(product.expected_state)
                if actual.get(key) != product.expected_state.get(key)
            )
            issues.append(
                ProjectionRebuildIssue(
                    code="REBUILT_PROJECTION_MISMATCH",
                    message=(
                        "freshly materialized products row differs from ledger"
                        + (f"; fields={','.join(fields)}" if fields else "")
                    ),
                    identity_key=identity_key,
                )
            )
        if row.accepted_observation_id != product.accepted_observation_id:
            issues.append(
                ProjectionRebuildIssue(
                    code="REBUILT_ACCEPTED_OBSERVATION_MISMATCH",
                    message="fresh projection accepted_observation_id differs from ledger",
                    identity_key=identity_key,
                )
            )

        rebuilt.append(
            RebuiltProjectionProduct(
                source=source,
                identity_key=identity_key,
                old_product_id=old_ids.get(identity_key),
                new_product_id=row.id,
                accepted_observation_id=row.accepted_observation_id,
                state=actual,
            )
        )

    detached = list(
        session.scalars(
            select(ProductHistoryRow.id).where(
                ProductHistoryRow.source == source,
                ProductHistoryRow.product_id.is_(None),
            )
        )
    )
    if detached:
        issues.append(
            ProjectionRebuildIssue(
                code="DETACHED_HISTORY_AFTER_REBUILD",
                message=f"{len(detached)} history row(s) remain detached from projection",
            )
        )

    # Every rebuilt identity must now own exactly the ledger histories discovered
    # before deletion. Surrogate ids may change; semantic identity may not.
    for product in ledger.products:
        linked = list(
            session.scalars(
                select(ProductHistoryRow.id).where(
                    ProductHistoryRow.source == source,
                    ProductHistoryRow.identity_key == product.identity_key,
                    ProductHistoryRow.product_id.is_not(None),
                )
            )
        )
        if tuple(linked) != product.history_ids:
            issues.append(
                ProjectionRebuildIssue(
                    code="HISTORY_RELINK_MISMATCH",
                    message="rebuilt projection does not own the original semantic history set",
                    identity_key=product.identity_key,
                )
            )

    history_count = len(
        list(
            session.scalars(
                select(ProductHistoryRow.id).where(ProductHistoryRow.source == source)
            )
        )
    )
    return ProjectionRebuildReport(
        source=source,
        products=tuple(rebuilt),
        history_rows=history_count,
        extraction=extraction,
        issues=tuple(issues),
    )
