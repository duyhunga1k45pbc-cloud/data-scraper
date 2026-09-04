# Data Scraper

## Goal

Collect external product data and maintain a reliable structured current state and history.

Current milestones:

- **M0 — Books to Scrape:** one static HTML source, end-to-end correctness loop.
- **M1 — ScrapeMe:** second HTML e-commerce source, shared `Product` state contract.
- **M2 — Scrapify JS:** one JSON payload can contain many product records and stable source IDs can be the best identity.
- **M3 — ScrapingSandbox:** richer e-commerce semantics: compare-at pricing, SKU, variants, variant stock, and preserved category cardinality.

## M3 finding

M2's product contract was still too narrow for richer e-commerce data.

ScrapingSandbox product pages expose product-level pricing plus a JSON snapshot containing:

```text
price
compareAtPrice
sku
inStock
category
variants[]
  ├── color
  ├── size
  ├── sku
  ├── inStock
  └── price
```

The shared product contract therefore now preserves:

```text
current product price
compare-at/original price
product SKU
all observed categories
variant identities/options
variant price
variant availability
```

A variant change is part of the trusted product state and can therefore produce an `UPDATE` + history entry.

## Core flow

```text
External Source
      ↓
Acquisition
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

## Current sources

```text
Books to Scrape   → static HTML
ScrapeMe          → static WooCommerce HTML
Scrapify JS       → public JSON endpoint observed behind JS storefront
ScrapingSandbox   → product HTML containing deterministic JSON preview
```

M3 still does **not** add Playwright. The required richer product evidence is present in the fetched HTML, so `httpx + BeautifulSoup + JSON parsing` remains sufficient.

## Identity

Products can use either:

```text
source + canonical_product_url
```

or:

```text
source + source_record_id
```

Variants currently live inside the parent product state and use a stable variant key, preferring SKU when available.

## M3 validation additions

```text
compare_at_price >= current price, when present
variant identity must exist
variant identities must be unique within one product
variant price must be valid and >= 0
variant availability must be recognized
```

No assumption is made that product-level price equals min/max variant price.

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

Migration `0004_m3_richer_product_semantics` adds product/observation fields for:

- compare-at price
- SKU
- full category list
- variant snapshots

Variants remain nested JSON in product state/history. They are not a separate table because M3 has no requirement for independent variant querying/history yet.

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

M3 live source:

```bash
RUN_LIVE=1 pytest -q tests/integration/test_scraping_sandbox_live.py
```

M3 live + PostgreSQL:

```bash
RUN_LIVE=1 RUN_POSTGRES=1 \
pytest -q tests/integration/test_scraping_sandbox_postgres_e2e.py
```

Full integration:

```bash
RUN_LIVE=1 RUN_POSTGRES=1 pytest -q tests/integration
```

## CLI

Scrape the M3 product:

```bash
python -m src.main scrape \
  https://scrapingsandbox.com/product/1
```

Inspect current state/history:

```bash
python -m src.main show \
  https://scrapingsandbox.com/product/1

python -m src.main history \
  https://scrapingsandbox.com/product/1
```

Existing M2 catalog commands remain available:

```bash
python -m src.main scrape-catalog scrapify-js
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
