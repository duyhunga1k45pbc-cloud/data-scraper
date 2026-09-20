#!/usr/bin/env bash
set -euo pipefail

if [ ! -d .git ]; then
  echo "ERROR: run this from the public data-scraper repository root."
  exit 1
fi

cat > README.md <<'EOF_README'
# Data Scraper

A reliability-focused Python data-ingestion system for collecting external product data and maintaining a trustworthy current state and history.

This public repository is a portfolio-oriented showcase. Detailed design records, reusable internal mechanisms, and production-specific implementation details are intentionally omitted.

## What this project demonstrates

The project focuses on correctness under conditions that commonly make long-running data pipelines unreliable:

- changing external source data
- delayed or out-of-order observations
- concurrent updates
- incomplete catalog acquisition
- retries and interrupted runs
- parser evolution
- stale or rebuildable derived state
- recovery after data loss
- browser-based acquisition when plain HTTP is insufficient

The main design goal is simple:

> Only validated and accepted observations may change trusted persisted state.

## High-level architecture

```text
External sources
      ↓
Acquisition
      ↓
Raw evidence
      ↓
Extraction / normalization
      ↓
Validation
      ↓
Trusted state transition
      ↓
Current product state
      ↓
Semantic history
      ↓
Read-only delivery
```

Operational concerns such as run tracking, retry handling, logging, and recovery are kept separate from product truth.

## Key properties

### Deterministic state handling

The system distinguishes between newly observed data, meaningful state changes, stale observations, and no-op observations. Historical source order or other presentation noise is not treated as a business-state change.

### Temporal correctness

An older observation may still be retained for traceability, but it cannot move trusted state backward in time.

### Concurrency safety

Concurrent updates are handled so state decisions are based on the latest committed information rather than on stale worker-local assumptions.

### Explicit acquisition completeness

Missing data is not automatically interpreted as disappearance. Absence only affects trusted state when the acquisition scope is known to be complete.

### Rebuildable derived state

The current-state projection is treated as rebuildable rather than as the only source of truth. Verification paths check that trusted state can be reproduced from durable historical evidence.

### Recovery verification

The project includes recovery-oriented tests and tooling that exercise rebuild and restore paths instead of assuming backups are correct merely because they exist.

### Version-aware extraction

Historical observations retain enough provenance to detect when current extraction behavior no longer reproduces previously accepted interpretations.

### Failure-aware operations

Runs have explicit lifecycle state, interrupted work can be identified, and retries are designed around existing idempotence and temporal-correctness guarantees.

### Browser acquisition boundary

Playwright is used only where JavaScript-rendered content requires it. Browser acquisition feeds the same downstream evidence and state pipeline rather than becoming a separate source of truth.

## Verification

The repository contains deterministic, integration, PostgreSQL, recovery, and opt-in live tests covering areas such as:

- state-transition semantics
- temporal ordering
- concurrent updates
- acquisition completeness
- semantic history
- projection replay and rebuild
- historical extraction verification
- clean-database recovery
- operational run lifecycle
- browser-based acquisition

Typical local test run:

```bash
pytest -q
```

PostgreSQL-backed integration tests are opt-in:

```bash
RUN_POSTGRES=1 pytest -q tests/integration
```

Browser and live-source checks are also opt-in so the deterministic suite remains reproducible.

## Technology

- Python
- PostgreSQL
- SQLAlchemy
- Alembic
- Pytest
- FastAPI / Uvicorn for read-only delivery
- Playwright for browser acquisition
- Docker Compose
- GitHub Actions

## Local development

Start PostgreSQL:

```bash
docker compose up -d postgres
```

Configure the database and apply migrations:

```bash
export DATABASE_URL='postgresql+psycopg://data_scraper:data_scraper@localhost:5433/data_scraper'
alembic upgrade head
```

Run the deterministic test suite:

```bash
pytest -q
```

## Scope

This repository is intended to demonstrate systems thinking around reliable external-data ingestion: evidence preservation, trustworthy state transitions, concurrency, recovery, verification, and operational failure handling.

It is not intended to publish a complete reusable production blueprint. Detailed architecture decisions, internal recovery algorithms, exact locking strategies, and other reusable implementation details are kept outside the public showcase.
EOF_README

if [ -d docs ]; then
  git rm -r docs
fi

# Remove common local-only artifacts if they somehow became tracked/untracked here.
rm -rf .pytest_cache
find . -type d -name __pycache__ -prune -exec rm -rf {} +

echo
echo "Sanitization staged locally. Nothing has been pushed yet."
echo
echo "Review:"
git status --short
echo
git diff --stat

echo
echo "If the diff looks right, run:"
echo '  git add -A'
echo '  git commit -m "docs: convert repository into public showcase"'
echo '  git push origin main'

echo
echo "Reminder: old detailed content remains in existing public Git history."
