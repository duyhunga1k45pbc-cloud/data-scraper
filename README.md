# Data Scraper

## Goal

Collect external book data and maintain a reliable structured state and history.

M0 uses **Books to Scrape** as the first source.

## Core flow

```text
External Source
      ↓
    Fetch
      ↓
 RawEvidence
      ↓
BookObservation
      ↓
  Normalize
      ↓
BookNormalizedData
      ↓
   Validate
      ↓
 ValidatedBook
      ↓
State Transition
      ↓
CurrentBookState
      ↓
  BookHistory
      ↓
    Deliver
```

The core rule is:

> Only validated and accepted data may change trusted persisted state.

The system keeps the representations separate so that a wrong result can be traced back through the exact evidence, extraction, normalization, validation, state decision, and history.

## M0 scope

Tracked fields:

- title
- price
- currency
- availability
- quantity, when available
- category
- canonical product URL

Identity for M0:

```text
source + canonical_product_url
```

## Documentation

The M0 architecture contract is in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## M0 technology

Planned only where required by the architecture:

- Python
- httpx
- BeautifulSoup + lxml
- Pydantic
- PostgreSQL
- SQLAlchemy
- Alembic
- pytest

## Non-goals for M0

M0 does not include:

- generic entity abstractions
- plugin/source-adapter frameworks
- fuzzy or cross-source identity resolution
- Redis or Celery
- Playwright
- LLM extraction
- alerts or dashboards

New mechanisms are added only when a new requirement, an observed failure mode, or an invariant that the current mechanism cannot preserve requires them.

## Live source smoke test

The normal test suite is deterministic and does not require network access.
To exercise the real acquisition boundary against Books to Scrape:

```bash
RUN_LIVE=1 pytest -q tests/integration/test_books_live.py
```

This verifies the live path through:

```text
External Source
→ HTTP Fetch
→ RawEvidence
→ BookObservation
→ BookNormalizedData
→ ValidatedBook
```

## M0 persistence

Persistence is implemented with SQLAlchemy and Alembic over four tables:

```text
raw_evidence
      ↓
book_observations
      ↓ accepted state decision
    books
      ↓
 book_history
```

`raw_evidence` preserves the exact fetched body. `book_observations` preserves both source-shaped and normalized values plus the state decision and validation errors. `books` contains the current trusted state. `book_history` records only accepted `CREATE` and `UPDATE` transitions and links each transition back to the observation that caused it.

The current-state mutation and corresponding history append are executed inside one database transaction.

### Local PostgreSQL

A minimal PostgreSQL service is provided in `compose.yaml`:

```bash
docker compose up -d postgres
export DATABASE_URL='postgresql+psycopg://data_scraper:data_scraper@localhost:5433/data_scraper'
alembic upgrade head
```

Then run the deterministic test suite:

```bash
pytest -q
```

To exercise persistence against PostgreSQL:

```bash
RUN_POSTGRES=1 pytest -q tests/integration/test_postgres_persistence.py
```

To combine the real external source with persisted state, use `persist_book_url(...)` from `src.storage.service` with a configured SQLAlchemy session factory.

## Live PostgreSQL end-to-end proof

With PostgreSQL running and migrated:

```bash
export DATABASE_URL='postgresql+psycopg://data_scraper:data_scraper@localhost:5433/data_scraper'
RUN_LIVE=1 RUN_POSTGRES=1 pytest -q tests/integration/test_live_postgres_e2e.py
```

This verifies the complete M0 path from the live Books to Scrape page through persisted current state and history.

