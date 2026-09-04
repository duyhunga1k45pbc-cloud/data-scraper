Data Scraper

Goal

Collect external book data and maintain a reliable structured state and history.

M0 uses Books to Scrape as the first source.

Core flow

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

The core rule is:

Only validated and accepted data may change trusted persisted state.

The system keeps the representations separate so that a wrong result can be traced back through the exact evidence, extraction, normalization, validation, state decision, and history.

M0 scope

Tracked fields:

title

price

currency

availability

quantity, when available

category

canonical product URL

Identity for M0:

source + canonical_product_url

Documentation

The M0 architecture contract is in docs/ARCHITECTURE.md.

M0 technology

Planned only where required by the architecture:

Python

httpx

BeautifulSoup + lxml

Pydantic

PostgreSQL

SQLAlchemy

Alembic

pytest

Non-goals for M0

M0 does not include:

generic entity abstractions

plugin/source-adapter frameworks

fuzzy or cross-source identity resolution

Redis or Celery

Playwright

LLM extraction

alerts or dashboards

New mechanisms are added only when a new requirement, an observed failure mode, or an invariant that the current mechanism cannot preserve requires them.