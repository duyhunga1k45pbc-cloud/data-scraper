from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.acquisition.models import RawEvidence
from src.extractors.registry import (
    ExtractorRuntimeNotFoundError,
    resolve_extractor_runtime,
)
from src.products.models import ProductObservation, ProductVariantObservation
from src.products.normalization import canonicalize_product_url

from .models import ProductObservationRow, RawEvidenceRow


@dataclass(frozen=True)
class ReextractionIssue:
    code: str
    message: str
    evidence_id: str
    extractor_version: str
    identity_key: str | None = None


@dataclass(frozen=True)
class ReextractedEvidence:
    evidence_id: str
    extractor_version: str
    implementation: str
    persisted_observations: int
    reextracted_observations: int


@dataclass(frozen=True)
class ReextractionReport:
    source: str
    evidence_groups: int
    evidence: tuple[ReextractedEvidence, ...]
    observations: int
    issues: tuple[ReextractionIssue, ...]

    @property
    def is_consistent(self) -> bool:
        return not self.issues


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _as_utc(value).isoformat()


def _source_record_id(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def _identity_projection(observation: ProductObservation) -> tuple[str, str | None, str | None]:
    """Project the raw identity fields onto the representation persisted pre-M11.

    M0-M10 did not keep ``source_record_id_raw`` and
    ``canonical_product_url_raw`` as separate columns. The persistence boundary
    kept their identity/locator projection instead. M11 therefore compares that
    projection for historical rows while comparing all other persisted raw
    extraction fields exactly.
    """

    source_record_id = _source_record_id(observation.source_record_id_raw)
    if observation.canonical_product_url_raw is not None:
        canonical_product_url = canonicalize_product_url(
            observation.canonical_product_url_raw
        )
    elif source_record_id is None:
        canonical_product_url = canonicalize_product_url(observation.source_url)
    else:
        canonical_product_url = None

    if source_record_id:
        identity_key = f"id:{source_record_id}"
    elif canonical_product_url:
        identity_key = f"url:{canonical_product_url}"
    else:
        identity_key = (
            f"rejected:{observation.source_record_id_raw or observation.source_url}:"
            f"{observation.title_raw or ''}"
        )
    return identity_key, source_record_id, canonical_product_url


def _raw_variant_payload(variant: ProductVariantObservation) -> dict[str, Any]:
    return {
        "sku_raw": variant.sku_raw,
        "price_raw": variant.price_raw,
        "availability_raw": variant.availability_raw,
        "options_raw": [list(pair) for pair in variant.options_raw],
    }


def _fresh_payload(observation: ProductObservation) -> dict[str, Any]:
    identity_key, source_record_id, canonical_product_url = _identity_projection(
        observation
    )
    return {
        "identity_key": identity_key,
        "source_record_id": source_record_id,
        "canonical_product_url": canonical_product_url,
        "extractor_version": observation.extractor_version,
        "source": observation.source,
        "source_url": observation.source_url,
        "observed_at": _iso(observation.observed_at),
        "title_raw": observation.title_raw,
        "price_raw": observation.price_raw,
        "compare_at_price_raw": observation.compare_at_price_raw,
        "currency_raw": observation.currency_raw,
        "availability_raw": observation.availability_raw,
        "category_raw": observation.category_raw,
        "sku_raw": observation.sku_raw,
        "categories_raw": list(observation.categories_raw),
        "variants_raw": [_raw_variant_payload(item) for item in observation.variants_raw],
    }


def _persisted_payload(row: ProductObservationRow) -> dict[str, Any]:
    return {
        "identity_key": row.identity_key,
        "source_record_id": row.source_record_id,
        "canonical_product_url": row.canonical_product_url,
        "extractor_version": row.extractor_version,
        "source": row.source,
        "source_url": row.source_url,
        "observed_at": _iso(row.observed_at),
        "title_raw": row.title_raw,
        "price_raw": row.price_raw,
        "compare_at_price_raw": row.compare_at_price_raw,
        "currency_raw": row.currency_raw,
        "availability_raw": row.availability_raw,
        "category_raw": row.category_raw,
        "sku_raw": row.sku_raw,
        "categories_raw": list(row.categories_raw or []),
        "variants_raw": list(row.variants_raw or []),
    }


def _payload_token(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _identity_from_token(token: str) -> str | None:
    try:
        value = json.loads(token)
    except json.JSONDecodeError:
        return None
    identity_key = value.get("identity_key") if isinstance(value, dict) else None
    return identity_key if isinstance(identity_key, str) else None


def _raw_evidence_from_row(row: RawEvidenceRow) -> RawEvidence:
    return RawEvidence(
        id=row.id,
        source_url=row.source_url,
        fetched_at=row.fetched_at,
        status_code=row.status_code,
        content_type=row.content_type,
        body=row.body,
        body_hash=row.body_hash,
    )


def verify_source_reextraction(
    session: Session,
    *,
    source: str,
    evidence_ids: set[str] | None = None,
) -> ReextractionReport:
    """Re-run the recorded extractor version against each persisted RawEvidence.

    Verification happens at the extraction boundary. For each
    ``(evidence_id, extractor_version)`` group, M11 resolves the historical
    runtime by explicit version, re-extracts once, and compares the complete
    persisted raw observation multiset. This handles both 1:1 and 1:N evidence
    cardinality without relying on processing order.
    """

    statement = select(ProductObservationRow).where(
        ProductObservationRow.source == source
    )
    if evidence_ids is not None:
        statement = statement.where(ProductObservationRow.evidence_id.in_(evidence_ids))
    statement = statement.order_by(
        ProductObservationRow.evidence_id,
        ProductObservationRow.extractor_version,
        ProductObservationRow.id,
    )
    rows = list(session.scalars(statement))

    grouped: dict[tuple[str, str], list[ProductObservationRow]] = defaultdict(list)
    for row in rows:
        grouped[(row.evidence_id, row.extractor_version)].append(row)

    issues: list[ReextractionIssue] = []
    verified: list[ReextractedEvidence] = []

    for (evidence_id, extractor_version), persisted_rows in sorted(grouped.items()):
        evidence_row = session.get(RawEvidenceRow, evidence_id)
        if evidence_row is None:
            issues.append(
                ReextractionIssue(
                    code="MISSING_RAW_EVIDENCE",
                    message="persisted observations reference missing RawEvidence",
                    evidence_id=evidence_id,
                    extractor_version=extractor_version,
                )
            )
            continue

        actual_hash = sha256(evidence_row.body.encode("utf-8")).hexdigest()
        if actual_hash != evidence_row.body_hash:
            issues.append(
                ReextractionIssue(
                    code="RAW_EVIDENCE_HASH_MISMATCH",
                    message="RawEvidence body no longer matches its persisted body_hash",
                    evidence_id=evidence_id,
                    extractor_version=extractor_version,
                )
            )

        try:
            runtime = resolve_extractor_runtime(
                source=source,
                version=extractor_version,
            )
        except ExtractorRuntimeNotFoundError as exc:
            issues.append(
                ReextractionIssue(
                    code="EXTRACTOR_RUNTIME_NOT_FOUND",
                    message=str(exc),
                    evidence_id=evidence_id,
                    extractor_version=extractor_version,
                )
            )
            continue

        try:
            extracted = tuple(runtime.extract(_raw_evidence_from_row(evidence_row)))
        except Exception as exc:  # source parser errors are part of verification output
            issues.append(
                ReextractionIssue(
                    code="REEXTRACTION_FAILED",
                    message=f"{type(exc).__name__}: {exc}",
                    evidence_id=evidence_id,
                    extractor_version=extractor_version,
                )
            )
            verified.append(
                ReextractedEvidence(
                    evidence_id=evidence_id,
                    extractor_version=extractor_version,
                    implementation=runtime.implementation,
                    persisted_observations=len(persisted_rows),
                    reextracted_observations=0,
                )
            )
            continue

        persisted_counter = Counter(
            _payload_token(_persisted_payload(row)) for row in persisted_rows
        )
        extracted_counter = Counter(
            _payload_token(_fresh_payload(observation)) for observation in extracted
        )

        for token, count in sorted((persisted_counter - extracted_counter).items()):
            issues.append(
                ReextractionIssue(
                    code="PERSISTED_OBSERVATION_NOT_REPRODUCED",
                    message=(
                        f"{count} persisted observation(s) are not reproduced by "
                        f"{runtime.implementation}"
                    ),
                    evidence_id=evidence_id,
                    extractor_version=extractor_version,
                    identity_key=_identity_from_token(token),
                )
            )

        for token, count in sorted((extracted_counter - persisted_counter).items()):
            issues.append(
                ReextractionIssue(
                    code="UNPERSISTED_REEXTRACTED_OBSERVATION",
                    message=(
                        f"{count} observation(s) produced by {runtime.implementation} "
                        "have no matching persisted extraction"
                    ),
                    evidence_id=evidence_id,
                    extractor_version=extractor_version,
                    identity_key=_identity_from_token(token),
                )
            )

        verified.append(
            ReextractedEvidence(
                evidence_id=evidence_id,
                extractor_version=extractor_version,
                implementation=runtime.implementation,
                persisted_observations=len(persisted_rows),
                reextracted_observations=len(extracted),
            )
        )

    return ReextractionReport(
        source=source,
        evidence_groups=len(grouped),
        evidence=tuple(verified),
        observations=len(rows),
        issues=tuple(issues),
    )
