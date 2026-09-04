# Data Scraper

## Goal

Collect external product data from supported sources and maintain a reliable structured current state and history.

M1 supports two sources in the same product-state pipeline:

- **Books to Scrape** — M0 baseline
- **ScrapeMe** — WooCommerce-style M1 source

## Core flow

```text
External Source
      ↓
    Fetch
      ↓
 RawEvidence
      ↓
Source Parser
      ↓
ProductObservation
      ↓
  Normalize
      ↓
ProductNormalizedData
      ↓
   Validate
      ↓
ValidatedProduct
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

Every trusted state can be traced back through history → observation → exact raw evidence.

## Why M1 changed the M0 design

The second source showed that `Book*` was source/domain vocabulary, while the shared business object is a **Product**. M1 therefore generalizes only the parts proven common by two sources:

```text
shared:
ProductObservation
ProductNormalizedData
ValidatedProduct
CurrentProductState
ProductHistory
state transitions
persistence
CLI

source-specific:
HTML parser
source host recognition
availability text normalization
```

M1 does **not** introduce a plugin framework or generic entity model.

ScrapeMe exposes multiple categories, while the M0 contract has one optional category field. M1 deliberately does not invent a primary category; that field is left unset for ScrapeMe until a real requirement justifies changing category cardinality.

## Identity

For M1:

```text
source + canonical_product_url
```

URL migration, fuzzy matching, and cross-source entity resolution remain out of scope.

## Persistence

Current M1 tables:

```text
raw_evidence
      ↓
product_observations
      ↓ accepted state decision
   products
      ↓
product_history
```

M1 migration `0002_m1_product_semantics` renames the M0 book-specific tables while preserving existing M0 data.

`raw_evidence` is committed first so exact external input survives a later parser/state failure. Observation + current-state mutation + history append commit together in the trusted-state transaction.

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

Live source tests:

```bash
RUN_LIVE=1 pytest -q tests/integration/test_books_live.py
RUN_LIVE=1 pytest -q tests/integration/test_scrapeme_live.py
```

PostgreSQL tests:

```bash
RUN_POSTGRES=1 pytest -q tests/integration/test_postgres_persistence.py
```

Full live + PostgreSQL M1 integration:

```bash
RUN_LIVE=1 RUN_POSTGRES=1 pytest -q tests/integration
```

## CLI

With `DATABASE_URL` configured, the CLI auto-detects the supported source from the URL.

Books to Scrape:

```bash
python -m src.main scrape \
  https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html
```

ScrapeMe:

```bash
python -m src.main scrape \
  https://scrapeme.live/shop/Charizard/
```

Read current state:

```bash
python -m src.main show https://scrapeme.live/shop/Charizard/
```

Read accepted state-transition history:

```bash
python -m src.main history https://scrapeme.live/shop/Charizard/
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
