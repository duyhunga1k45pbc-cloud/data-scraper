from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256


@dataclass(frozen=True)
class RawEvidence:
    id: str
    source_url: str
    fetched_at: datetime
    status_code: int
    content_type: str
    body: str
    body_hash: str

    @classmethod
    def capture(
        cls,
        *,
        evidence_id: str,
        source_url: str,
        fetched_at: datetime,
        status_code: int,
        content_type: str,
        body: str,
    ) -> "RawEvidence":
        return cls(
            id=evidence_id,
            source_url=source_url,
            fetched_at=fetched_at,
            status_code=status_code,
            content_type=content_type,
            body=body,
            body_hash=sha256(body.encode("utf-8")).hexdigest(),
        )
