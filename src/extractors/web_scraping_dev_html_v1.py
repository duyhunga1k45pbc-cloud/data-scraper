from __future__ import annotations

from src.acquisition.models import RawEvidence
from src.products.models import ProductObservation
from src.web_scraping_dev.parser import EXTRACTOR_VERSION, SOURCE, parse_product_evidence


def extract_observations(evidence: RawEvidence) -> tuple[ProductObservation, ...]:
    """M11-retained runtime for web-scraping-dev-html-v1."""
    return parse_product_evidence(evidence)
