from __future__ import annotations

from datetime import datetime

import httpx
from sqlalchemy.orm import Session, sessionmaker

from src.acquisition.fetch import DEFAULT_TIMEOUT_SECONDS, fetch_url
from src.acquisition.models import RawEvidence
from src.storage.service import PersistedProductRun, persist_product_observations

from .parser import parse_catalog


STOREFRONT_URL = "https://scrapifydatalabs.com/playground/js-rendered"
DATA_URL = "https://scrapifydatalabs.com/data/products.json"


def fetch_catalog_evidence(
    *,
    client: httpx.Client | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    evidence_id: str | None = None,
    fetched_at: datetime | None = None,
) -> RawEvidence:
    # M2 finding: the storefront itself is JS-rendered, but its public network
    # request exposes the deterministic source data. Prefer that endpoint over
    # browser automation until a source requires browser-only evidence.
    return fetch_url(
        DATA_URL,
        client=client,
        timeout_seconds=timeout_seconds,
        evidence_id=evidence_id,
        fetched_at=fetched_at,
    )


def persist_catalog(
    session_factory: sessionmaker[Session],
    *,
    client: httpx.Client | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    evidence_id: str | None = None,
    fetched_at: datetime | None = None,
    changed_at: datetime | None = None,
) -> tuple[PersistedProductRun, ...]:
    evidence = fetch_catalog_evidence(
        client=client,
        timeout_seconds=timeout_seconds,
        evidence_id=evidence_id,
        fetched_at=fetched_at,
    )
    observations = parse_catalog(evidence)
    return persist_product_observations(
        session_factory,
        evidence,
        observations,
        changed_at=changed_at,
    )
