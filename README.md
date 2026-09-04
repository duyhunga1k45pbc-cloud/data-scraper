# Data Scraper

## Goal

Collect external product data and maintain a reliable structured current state and history.

Current milestones:

- **M0 — Books to Scrape:** one static HTML source, end-to-end correctness loop.
- **M1 — ScrapeMe:** second HTML e-commerce source, shared `Product` state contract.
- **M2 — Scrapify JS storefront:** dynamic page whose product grid is injected by JavaScript from a public JSON request.

## M2 finding

The Scrapify storefront page is dynamic, but the deterministic source data is available from its public network endpoint:

```text
https://scrapifydatalabs.com/playground/js-rendered
        ↓ JavaScript GET
https://scrapifydatalabs.com/data/products.json
```

M2 therefore does **not** add Playwright. The mechanism is:

```text
Dynamic storefront
      ↓ inspect acquisition boundary
Public JSON endpoint
      ↓ httpx
RawEvidence (one JSON response)
      ↓
Many ProductObservations
      ↓
Normalize / Validate
      ↓
Shared Product State + History
```

This also proved two M1 assumptions were too narrow:

1. one `RawEvidence` can contain many product records;
2. a stable source record ID can be a better identity than a product URL.

## Core flow

```text
External Source
      ↓
Acquisition mechanism selected from observed source behavior
      ↓
RawEvidence
      ↓
1..N ProductObservation
      ↓
Normalize
      ↓
Validate
      ↓
State Transition
      ↓
CurrentProductState
      ↓
ProductHistory
      ↓
CLI
```

Core rule:

> Only validated and accepted product data may change trusted persisted state.

## Identity

M2 supports either:

```text
source + canonical_product_url
```

or:

```text
source + source_record_id
```

Internally both become a stable `identity_key`.

## Persistence

```text
raw_evidence
      ↓ 1:N
product_observations
      ↓ accepted state decision
products
      ↓
product_history
```

Migration `0003_m2_multi_record_identity` preserves M0/M1 data while adding:

- `identity_key`
- optional `source_record_id`
- multi-record observation uniqueness
- optional product URL for ID-identified records
- raw currency provenance for JSON sources

## Local PostgreSQL

```bash
docker compose up -d postgres
export DATABASE_URL='postgresql+psycopg://data_scraper:data_scraper@localhost:5433/data_scraper'
alembic upgrade head
```

## Tests

Deterministic suite:

```bash
pytest -q
```

M2 live acquisition tests:

```bash
RUN_LIVE=1 pytest -q tests/integration/test_scrapify_js_live.py
```

M2 live + PostgreSQL:

```bash
RUN_LIVE=1 RUN_POSTGRES=1 pytest -q tests/integration/test_scrapify_js_postgres_e2e.py
```

Full integration:

```bash
RUN_LIVE=1 RUN_POSTGRES=1 pytest -q tests/integration
```

## CLI

Existing URL-identified products still work:

```bash
python -m src.main scrape \
  https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html

python -m src.main scrape \
  https://scrapeme.live/shop/Charizard/
```

Scrape the M2 JS storefront through its observed JSON acquisition path:

```bash
python -m src.main scrape-catalog scrapify-js
```

Inspect a source-ID-identified product:

```bash
python -m src.main show-record scrapify_js p-1001
python -m src.main history-record scrapify_js p-1001
```

## Architecture contract

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Freeze rule

A new mechanism is added only when required by:

```text
new business requirement
OR
observed failure mode
OR
current mechanism cannot preserve an invariant
```
