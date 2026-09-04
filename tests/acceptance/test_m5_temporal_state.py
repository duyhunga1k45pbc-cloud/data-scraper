from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from src.acquisition.models import RawEvidence
from src.products.models import StateDecision
from src.products.service import process_product_evidence


FIXTURE = Path(__file__).parents[1] / "fixtures" / "scraping_sandbox_product.html"
URL = "https://scrapingsandbox.com/product/1"
T0 = datetime(2026, 9, 5, 6, 0, tzinfo=timezone.utc)
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


def test_m5_older_valid_observation_is_stale_and_cannot_move_state_backward() -> None:
    base = _base_payload()
    newer_time = T0 + timedelta(minutes=5)
    current_run = process_product_evidence(
        _evidence("m5-current", base, newer_time),
        changed_at=newer_time,
    )
    assert current_run.transition.current_state is not None
    current = current_run.transition.current_state

    older = deepcopy(base)
    older["price"] = 99.99
    stale_run = process_product_evidence(
        _evidence("m5-stale", older, T0),
        current=current,
        changed_at=T0 + timedelta(minutes=10),
    )

    assert stale_run.transition.decision == StateDecision.STALE
    assert stale_run.transition.current_state == current
    assert stale_run.transition.current_state.price == Decimal("155.62")
    assert stale_run.transition.current_state.observed_at == newer_time
    assert stale_run.transition.history_entry is None


def test_m5_older_equivalent_observation_is_still_classified_as_stale() -> None:
    base = _base_payload()
    newer_time = T0 + timedelta(minutes=5)
    current_run = process_product_evidence(
        _evidence("m5-current-same", base, newer_time),
        changed_at=newer_time,
    )
    assert current_run.transition.current_state is not None

    stale_run = process_product_evidence(
        _evidence("m5-stale-same", base, T0),
        current=current_run.transition.current_state,
        changed_at=T0 + timedelta(minutes=10),
    )

    assert stale_run.transition.decision == StateDecision.STALE
    assert stale_run.transition.history_entry is None


def test_m5_newer_observation_can_update_after_a_stale_attempt() -> None:
    base = _base_payload()
    t1 = T0 + timedelta(minutes=5)
    current_run = process_product_evidence(
        _evidence("m5-sequence-current", base, t1),
        changed_at=t1,
    )
    assert current_run.transition.current_state is not None
    current = current_run.transition.current_state

    older = deepcopy(base)
    older["price"] = 99.99
    stale = process_product_evidence(
        _evidence("m5-sequence-stale", older, T0),
        current=current,
        changed_at=T0 + timedelta(minutes=10),
    )
    assert stale.transition.decision == StateDecision.STALE

    newer = deepcopy(base)
    newer["price"] = 149.99
    t2 = T0 + timedelta(minutes=6)
    accepted = process_product_evidence(
        _evidence("m5-sequence-newer", newer, t2),
        current=stale.transition.current_state,
        changed_at=t2,
    )

    assert accepted.transition.decision == StateDecision.UPDATE
    assert accepted.transition.current_state is not None
    assert accepted.transition.current_state.price == Decimal("149.99")
    assert accepted.transition.current_state.observed_at == t2
    assert accepted.transition.history_entry is not None
