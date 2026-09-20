# Data Scraper

A Python data-ingestion project focused on reliable acquisition, parsing, normalization, validation, and trustworthy handling of external product data.

This repository is a **portfolio-oriented public showcase**. It contains representative implementation and tests while intentionally omitting reusable production internals and detailed architecture mechanisms.

## Problem

External data pipelines become difficult when source data changes, observations arrive in unexpected forms, identities are inconsistent, or incomplete acquisition is mistaken for real business-state changes.

The larger project was developed around a simple principle:

> Only validated and accepted observations should be allowed to affect trusted state.

## Public Code Sample

The public repository includes representative implementations for:

- HTTP acquisition
- HTML and JSON parsing
- product normalization
- source identity handling
- validation
- multiple external-source adapters
- deterministic unit tests

High-level flow:

```text
External source
      ↓
Acquisition
      ↓
Parsing
      ↓
Normalization
      ↓
Validation
      ↓
Structured observation
```

## Engineering Considerations

The complete project explored reliability concerns including:

- delayed and out-of-order observations
- concurrent state changes
- incomplete catalog acquisition
- meaningful-change detection
- rebuildable derived state
- recovery verification
- parser evolution
- interrupted execution and retries
- browser-based acquisition for JavaScript-rendered sources

These mechanisms are intentionally described only at a high level in this public showcase.

## Representative Source Coverage

The sample code demonstrates different acquisition and parsing shapes:

- static HTML products
- WooCommerce-style HTML
- JSON product catalogs
- richer product representations with categories and variants

This keeps source-specific parsing separate from shared normalization and validation concepts.

## Design Approach

The project follows several recurring principles:

- external data is treated as evidence, not automatically as trusted state
- parsing, normalization, and validation are separate concerns
- source-specific behavior stays behind explicit adapters
- identity should remain stable even when source presentation changes
- deterministic behavior should be testable independently of live sources
- additional mechanisms should be introduced in response to real failure modes rather than added preemptively

The public repository demonstrates these ideas through the acquisition and transformation layers without exposing the complete production architecture.

## Repository Structure

```text
src/
├── acquisition/
│   ├── fetch.py
│   └── models.py
│
├── books/
│   ├── models.py
│   ├── normalization.py
│   ├── parser.py
│   └── validation.py
│
├── products/
│   ├── models.py
│   ├── normalization.py
│   ├── source.py
│   └── validation.py
│
├── scrapeme/
│   └── parser.py
│
├── scrapify_js/
│   └── parser.py
│
├── scraping_sandbox/
│   └── parser.py
│
└── extractors/
    ├── books_to_scrape_v1.py
    ├── scrapeme_live_v2.py
    ├── scrapify_js_json_v1.py
    └── scraping_sandbox_json_v1.py

tests/
├── fixtures/
│   ├── book_product.html
│   ├── scrapeme_product.html
│   ├── scrapify_products.json
│   └── scraping_sandbox_product.html
│
└── unit/
    ├── test_book_parser.py
    ├── test_fetch.py
    ├── test_m3_richer_product_normalization.py
    ├── test_m3_richer_product_validation.py
    ├── test_product_normalization.py
    ├── test_product_source.py
    ├── test_scrapeme_parser.py
    ├── test_scrapify_js_parser.py
    ├── test_scraping_sandbox_parser.py
    └── test_validation.py
```

The public tree intentionally contains only a representative slice of the full system.

## Tests

The public repository includes a compact deterministic test suite covering representative behavior such as:

- HTML parsing
- JSON parsing
- product normalization
- validation
- product identity and source handling
- richer product semantics
- HTTP acquisition behavior

Run the tests with:

```bash
pytest -q
```

At the time this showcase was prepared, the public test suite contained:

```text
16 passed
```

## Technology

The public showcase uses:

- Python
- HTTPX
- Beautiful Soup
- lxml
- Pytest
- GitHub Actions

The complete private implementation also contains persistence, operational reliability, recovery, and browser-acquisition components that are intentionally not published here.

## Local Development

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it on Linux or WSL:

```bash
source .venv/bin/activate
```

Install the project:

```bash
python -m pip install --upgrade pip
pip install -e .
```

Run tests:

```bash
pytest -q
```

## What Is Intentionally Omitted

The complete implementation contains additional work around areas such as:

- persistence architecture
- concurrent state transitions
- catalog completeness
- semantic history
- projection replay and rebuild
- recovery verification
- historical extraction behavior
- operational run lifecycle
- retry and interruption handling
- browser-based acquisition
- read-only delivery interfaces
- observability

These components are intentionally excluded from the public repository.

The public version is designed to show implementation quality and engineering approach without publishing the complete reusable production architecture.

## Portfolio Scope

The purpose of this repository is to demonstrate:

- decomposition of an external-data problem
- clean acquisition and parsing boundaries
- explicit normalization and validation
- deterministic testing
- source-specific adapters behind shared domain concepts
- reliability-oriented systems thinking
- separation between raw external data and trusted internal representations

It is **not** intended to publish a complete reusable production blueprint.

Detailed persistence design, concurrency mechanisms, recovery algorithms, completeness mechanisms, versioned extraction infrastructure, and other reusable production internals are intentionally kept outside the public repository.