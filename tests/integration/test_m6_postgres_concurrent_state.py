from __future__ import annotations

import json
import os
import re
import threading
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from src.acquisition.models import RawEvidence
from src.products.models import StateDecision
from src.storage import service as storage_service
from src.storage.database import create_database_engine, create_session_factory
from src.storage.models import ProductHistoryRow, ProductObservationRow, ProductRow, RawEvidenceRow
from src.storage.service import persist_product_evidence


FIXTURE = Path(__file__).parents[1] / "fixtures" / "scraping_sandbox_product.html"
URL = "https://scrapingsandbox.com/product/1"
SOURCE = "scraping_sandbox"
T0 = datetime(2026, 9, 5, 9, 0, tzinfo=timezone.utc)
_PRE_RE = re.compile(r"(<pre>)(.*?)(</pre>)", re.DOTALL)


def _base_payload() -> dict[str, object]:
    body = FIXTURE.read_text(encoding="utf-8")
    match = _PRE_RE.search(body)
    assert match is not None
    return json.loads(match.group(2))


def _evidence(evidence_id: str, payload: dict[str, object], at: datetime) -> RawEvidence:
    body = FIXTURE.read_text(encoding="utf-8")
    body = _PRE_RE.sub(
        rf"\1{json.dumps(deepcopy(payload), indent=2)}\3",
        body,
        count=1,
    )
    return RawEvidence.capture(
        evidence_id=evidence_id,
        source_url=URL,
        fetched_at=at,
        status_code=200,
        content_type="text/html",
        body=body,
    )


@pytest.mark.postgres
@pytest.mark.skipif(
    os.getenv("RUN_POSTGRES") != "1" or not os.getenv("DATABASE_URL"),
    reason="set RUN_POSTGRES=1 and DATABASE_URL",
)
def test_m6_concurrent_older_worker_cannot_overwrite_newer_trusted_state(monkeypatch) -> None:
    """INV-13: concurrent transitions must re-read serialized trusted state.

    The synchronization deliberately recreates the pre-M6 race:

    1. newer worker reads the current state;
    2. older worker is started while newer is still inside its transaction;
    3. without a row lock both workers can compute UPDATE from the same old state;
    4. older is forced to apply after newer and would overwrite it.

    With M6 ``SELECT ... FOR UPDATE``, the older worker cannot read until the
    newer transaction commits. It therefore sees the newer trusted state and is
    classified STALE instead of UPDATE.
    """
    engine = create_database_engine(os.environ["DATABASE_URL"])
    session_factory = create_session_factory(engine)

    try:
        with session_factory() as session:
            with session.begin():
                product = session.scalar(
                    select(ProductRow).where(
                        ProductRow.source == SOURCE,
                        ProductRow.source_record_id == "1",
                    )
                )
                if product is not None:
                    session.execute(
                        delete(ProductHistoryRow).where(ProductHistoryRow.product_id == product.id)
                    )
                    session.delete(product)
                session.execute(
                    delete(ProductObservationRow).where(ProductObservationRow.source == SOURCE)
                )
                session.execute(
                    delete(RawEvidenceRow).where(RawEvidenceRow.source_url == URL)
                )

        base = _base_payload()
        seed = persist_product_evidence(
            session_factory,
            _evidence("m6-pg-seed", base, T0),
            changed_at=T0,
        )
        assert seed.transition.decision == StateDecision.CREATE

        newer_payload = deepcopy(base)
        newer_payload["price"] = 166.00
        older_payload = deepcopy(base)
        older_payload["price"] = 144.00

        newer_time = T0 + timedelta(minutes=5)
        older_time = T0 + timedelta(minutes=3)

        newer_read = threading.Event()
        older_read = threading.Event()
        newer_committed = threading.Event()

        original_row_to_current_state = storage_service.row_to_current_state
        original_apply_state_transition = storage_service.apply_state_transition

        def synchronized_row_to_current_state(row):
            state = original_row_to_current_state(row)
            worker = threading.current_thread().name
            if worker == "m6-newer":
                newer_read.set()
                # Pre-M6, the older worker reaches this point too and releases us.
                # M6 blocks it at SELECT FOR UPDATE, so timeout lets newer commit.
                older_read.wait(timeout=0.5)
            elif worker == "m6-older":
                older_read.set()
            return state

        def ordered_apply_state_transition(*args, **kwargs):
            if threading.current_thread().name == "m6-older":
                # Pre-M6 this forces the stale UPDATE to be applied after newer
                # commits, reproducing the lost-update/temporal-regression bug.
                newer_committed.wait(timeout=2.0)
            return original_apply_state_transition(*args, **kwargs)

        monkeypatch.setattr(
            storage_service,
            "row_to_current_state",
            synchronized_row_to_current_state,
        )
        monkeypatch.setattr(
            storage_service,
            "apply_state_transition",
            ordered_apply_state_transition,
        )

        results: dict[str, object] = {}
        errors: dict[str, BaseException] = {}

        def run_newer() -> None:
            try:
                results["newer"] = persist_product_evidence(
                    session_factory,
                    _evidence("m6-pg-newer", newer_payload, newer_time),
                    changed_at=newer_time,
                )
            except BaseException as exc:  # pragma: no cover - diagnostic path
                errors["newer"] = exc
            finally:
                newer_committed.set()

        def run_older() -> None:
            try:
                results["older"] = persist_product_evidence(
                    session_factory,
                    _evidence("m6-pg-older", older_payload, older_time),
                    changed_at=T0 + timedelta(minutes=6),
                )
            except BaseException as exc:  # pragma: no cover - diagnostic path
                errors["older"] = exc

        newer_thread = threading.Thread(target=run_newer, name="m6-newer")
        older_thread = threading.Thread(target=run_older, name="m6-older")

        newer_thread.start()
        assert newer_read.wait(timeout=2.0), "newer worker never reached current-state read"
        older_thread.start()

        newer_thread.join(timeout=5.0)
        older_thread.join(timeout=5.0)

        assert not newer_thread.is_alive(), "newer worker deadlocked"
        assert not older_thread.is_alive(), "older worker deadlocked"
        assert not errors, errors

        newer = results["newer"]
        older = results["older"]
        assert newer.transition.decision == StateDecision.UPDATE
        assert older.transition.decision == StateDecision.STALE

        with session_factory() as session:
            product = session.scalar(
                select(ProductRow).where(
                    ProductRow.source == SOURCE,
                    ProductRow.source_record_id == "1",
                )
            )
            assert product is not None

            history = list(
                session.scalars(
                    select(ProductHistoryRow)
                    .where(ProductHistoryRow.product_id == product.id)
                    .order_by(ProductHistoryRow.id)
                )
            )
            observations = list(
                session.scalars(
                    select(ProductObservationRow)
                    .where(ProductObservationRow.source == SOURCE)
                    .order_by(ProductObservationRow.id)
                )
            )

            assert product.price == Decimal("166.00")
            assert product.observed_at == newer_time
            assert product.accepted_observation_id == newer.observation_id
            assert [row.decision for row in history] == [
                StateDecision.CREATE.value,
                StateDecision.UPDATE.value,
            ]
            assert [row.state_decision for row in observations] == [
                StateDecision.CREATE.value,
                StateDecision.UPDATE.value,
                StateDecision.STALE.value,
            ]
    finally:
        engine.dispose()
