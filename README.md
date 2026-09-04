# Data Scraper

## Goal

Collect external product data and maintain a reliable structured current state and history.

Current milestones:

- **M0 — Books to Scrape:** one static HTML source, end-to-end correctness loop.
- **M1 — ScrapeMe:** second HTML e-commerce source, shared `Product` state contract.
- **M2 — Scrapify JS:** one evidence payload can contain many product records and stable source IDs can be the best identity.
- **M3 — ScrapingSandbox:** richer product semantics: compare-at pricing, SKU, categories, variants, and variant stock/price.
- **M3.1 — identity vs locator:** URL lookup is separated from primary product identity.
- **M4 — semantic change history:** trusted history records meaningful product changes while ignoring source presentation-order noise.

## M4 finding

The M3 state comparator treated variant tuple order as business meaning. Reversing the same variant records therefore produced a false `UPDATE` even though the product had not changed.

M4 changes the state comparison contract:

```text
meaningful product change
→ UPDATE + history

same categories/variants in a different source order
→ NO_CHANGE
→ no history
```

Raw observations still preserve source order for traceability. Only the **trusted-state comparison** treats category membership, variant membership, and named variant-option order as order-insensitive semantics.

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

M4 strengthens that rule:

> History records business-state changes, not source presentation-order changes.

## Current sources

```text
Books to Scrape   → static HTML
ScrapeMe          → static WooCommerce HTML
Scrapify JS       → public JSON endpoint observed behind JS storefront
ScrapingSandbox   → product HTML containing deterministic JSON preview
```

No browser automation is required by the current evidence paths.

## Change semantics covered by M4

The deterministic M4 replay tests exercise the same ScrapingSandbox product across controlled snapshots:

```text
product price changed         → UPDATE
compare-at price removed      → UPDATE
variant stock changed         → UPDATE
variant added/removed         → UPDATE
variant order only changed    → NO_CHANGE
category order only changed   → NO_CHANGE
same changed snapshot replayed→ NO_CHANGE
```

A history entry stores both `previous_state` and `new_state`, so each accepted transition remains explainable.

## Identity

Products can use either:

```text
source + canonical_product_url
```

or:

```text
source + source_record_id
```

A stable source record ID remains the primary identity when available. A canonical URL may still be used as an alternate lookup locator.

Variants remain nested inside the parent product state and use a stable local key, preferring SKU when available.

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

M4 requires **no schema migration**. The existing full-state snapshots are sufficient; only semantic state comparison changed.

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

M4 deterministic semantic-history tests:

```bash
pytest -q \
  tests/acceptance/test_m4_semantic_change_history.py \
  tests/acceptance/test_m4_semantic_change_persistence.py
```

M4 PostgreSQL change-over-time test:

```bash
RUN_POSTGRES=1 \
pytest -q tests/integration/test_m4_postgres_change_history.py
```

Full integration suite, including live sources:

```bash
RUN_LIVE=1 RUN_POSTGRES=1 pytest -q tests/integration
```

## CLI

Scrape a product:

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

M2 catalog commands remain available:

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
