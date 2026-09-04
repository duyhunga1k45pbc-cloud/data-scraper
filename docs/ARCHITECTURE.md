# Data Scraper — Architecture Contract

## 1. Current scope: M1

M0 proved one trustworthy observation-to-state loop using Books to Scrape.

M1 adds a second e-commerce-shaped source, ScrapeMe, to discover what actually generalizes. M1 is not a generic scraping framework.

Supported sources:

```text
books.toscrape.com → books_to_scrape
scrapeme.live      → scrapeme_live
```

## 2. Business goal

> Collect external product data and maintain a reliable structured current state and history.

Core business requirements:

**BR-01 — Acquire**  
Collect product data from a supported external source.

**BR-02 — Structure**  
Extract and normalize required fields into a defined product schema.

**BR-03 — Data state**  
Explain which representation data is in, whether it was accepted, and why.

**BR-04 — Current trusted state**  
Maintain one trusted current state per source product identity. Invalid/failed data must not silently overwrite it.

**BR-05 — History**  
Preserve accepted trusted state transitions.

**BR-06 — Deliver**  
Expose current state and history as structured CLI output.

## 3. Current architecture

```text
External Source
      ↓
    Fetch
      ↓
┌─────────────────┐
│   RawEvidence   │
│ exact response  │
└────────┬────────┘
         ↓ source-specific extraction
┌────────────────────┐
│ ProductObservation │
└─────────┬──────────┘
          ↓ normalization
┌───────────────────────┐
│ ProductNormalizedData │
└───────────┬───────────┘
            ↓ validation
┌──────────────────┐
│ ValidatedProduct │
└────────┬─────────┘
         ↓
   State Transition
 ┌───────┼─────────────┐
 │       │             │
CREATE NO_CHANGE     UPDATE
 │                     │
 └──────────┬──────────┘
            ↓
 CurrentProductState
            ↓
      ProductHistory
            ↓
           CLI
```

Validation failure:

```text
ProductNormalizedData
        ↓
      REJECT
        ↓
current state unchanged
history unchanged
```

## 4. Representation boundaries

```text
RawEvidence
!= ProductObservation
!= ProductNormalizedData
!= ValidatedProduct
!= CurrentProductState
```

### RawEvidence

Purpose:

> Preserve the exact input required to verify/replay extraction.

```text
id
source_url
fetched_at
status_code
content_type
body
body_hash
```

### ProductObservation

Source-shaped interpretation of evidence:

```text
evidence_id
extractor_version
source
source_url
observed_at

title_raw
price_raw
availability_raw
category_raw
```

Observation is not trusted business data.

### ProductNormalizedData

Typed/normalized representation:

```text
source
canonical_product_url
observed_at
title
price
currency
availability
quantity
category
```

Normalization answers whether a representation can be converted. It does not decide whether the resulting business meaning is valid.

### ValidatedProduct

The domain boundary accepted by state-transition logic.

```text
Only ValidatedProduct may enter a state-changing decision.
```

### CurrentProductState

The current trusted representation used by downstream consumers. It is not simply the latest scrape result.

### ProductHistory

Contains only accepted `CREATE` and `UPDATE` transitions. Failed/rejected/no-change observations do not become trusted history entries.

## 5. M1 source boundary

The second source provided evidence for a small shared `Product` contract, but not for a plugin framework.

### Shared across both sources

```text
ProductObservation shape
price/currency domain type
availability domain type
validation semantics
identity rule
state transitions
current-state persistence
history
traceability
CLI delivery
```

### Still source-specific

```text
HTML selectors / parser
extractor version
source host recognition
availability text shape
```

Current availability examples:

```text
Books to Scrape:
"In stock (22 available)"
→ IN_STOCK, quantity=22

ScrapeMe:
"31 in stock"
→ IN_STOCK, quantity=31
```

M1 handles these explicitly. No source-adapter framework is introduced yet.

## 6. M1 schema decision: category

Books to Scrape exposes one book category. ScrapeMe/WooCommerce can expose multiple categories.

The M0 contract contains one optional `category` field. M1 does not guess which ScrapeMe category is primary, so the shared category field is left unset for that source.

This is an observed schema mismatch, not a reason by itself to invent a larger category abstraction. A future business requirement may justify changing the contract to multiple categories.

## 7. Validation

Field rules:

```text
title
- required
- non-empty

price
- required
- parseable Decimal
- >= 0

currency
- recognized

availability
- recognized

quantity
- if present, >= 0
```

Cross-field rule:

```text
OUT_OF_STOCK + quantity > 0
→ invalid
```

Identity validity:

```text
source must be supported
canonical URL must belong to the configured host for that source
```

Core distinction:

```text
Parseable != Valid
```

## 8. Identity

M1 identity remains:

```text
source + canonical_product_url
```

This is enough for the two current sources.

Deferred until observed need:

```text
URL migration
SKU-based identity
fuzzy identity
cross-source entity resolution
```

## 9. State transitions

### CREATE

```text
no current state
+ ValidatedProduct
→ create current state
→ append initial history
```

### NO_CHANGE

```text
current state
+ equivalent ValidatedProduct
→ state unchanged
→ no history entry
```

### UPDATE

```text
current state
+ different ValidatedProduct
→ update current state
→ append exactly one history entry
```

### REJECT

```text
invalid normalized data
→ current state unchanged
→ history unchanged
```

## 10. Invariants

**INV-01**  
Only validated + accepted data may modify trusted state.

**INV-02**  
Invalid/failed data must not modify current trusted state.

**INV-03**  
One `(source, canonical_product_url)` identity has at most one current state.

**INV-04**  
Persisted current state must satisfy domain validation.

**INV-05**  
Current-state update + history append form one atomic trusted-state transaction.

**INV-06**  
Reprocessing equivalent state must not create duplicate trusted transitions/history.

**INV-07**  
History must not contain a transition trusted state never actually underwent.

## 11. Persistence

M1 persistence:

```text
raw_evidence
      ↓
product_observations
      ↓ accepted
   products
      ↓
product_history
```

Meaning:

| Table | Question answered |
|---|---|
| `raw_evidence` | What exact response did the source return? |
| `product_observations` | What did the extractor/normalizer interpret from it? |
| `products` | What does the system currently trust? |
| `product_history` | How did trusted state actually change? |

M1 migration `0002_m1_product_semantics` renames M0's book-specific tables while preserving existing data.

Raw evidence commits first. If later extraction/state work fails, exact evidence remains available for divergence tracing.

Observation + current-state mutation + history append are committed together in the trusted-state transaction.

## 12. Divergence tracing

```text
RawEvidence
    ↓
ProductObservation
    ↓
ProductNormalizedData
    ↓
ValidatedProduct / validation result
    ↓
State Decision
    ↓
CurrentProductState
    ↓
ProductHistory
```

A wrong persisted value can therefore be traced to the first boundary where representation stopped corresponding to its input.

## 13. M1 acceptance evidence

Deterministic tests must prove at least:

```text
Books source still reaches the shared Product state contract.
ScrapeMe source reaches the same Product state contract.
Both sources persist into the same products/history model.
Same state remains idempotent.
Invalid data cannot mutate trusted state.
State update + history append rollback together on failure.
Unsupported source host is rejected before fetch.
```

Live tests may additionally prove:

```text
books.toscrape.com → shared Product state
scrapeme.live      → shared Product state
live source → PostgreSQL → trace back to RawEvidence
```

## 14. Current code boundaries

```text
src/
├── acquisition/
│   ├── fetch.py
│   └── models.py
├── products/
│   ├── models.py
│   ├── normalization.py
│   ├── validation.py
│   ├── state.py
│   ├── source.py
│   └── service.py
├── books/
│   └── parser.py          # Books source parser + M0 compatibility wrappers
├── scrapeme/
│   └── parser.py          # ScrapeMe source parser
├── storage/
│   ├── models.py
│   ├── repositories.py
│   └── service.py
└── main.py
```

`books/` compatibility wrappers remain temporarily so the M0 contracts/tests continue to prove backward behavior while M1 introduces shared Product semantics.

## 15. Explicit non-goals

Do not add without new evidence:

```text
GenericEntity
plugin/source-adapter framework
fuzzy identity resolution
cross-source entity resolution
variant model
sale/original-price model
Redis
Celery
Playwright
LLM extraction
alerts
dashboard
raw-evidence retention/dedup/object storage
```

## 16. Development loop

```text
Business Requirements
        ↓
Data Meaning
        ↓
Validation
        ↓
Invariants
        ↓
State Transition Rules
        ↓
Architecture
        ↓
Acceptance Tests
        ↓
Run against reality
        ↓
Observed Failure Modes
        ↓
Architecture evolves only if required
```

## 17. Freeze rule

A new mechanism is added only when at least one is true:

```text
new business requirement
OR
observed failure mode
OR
current mechanism cannot preserve an invariant
```

M1 deliberately stops at two supported sources and one shared Product contract. A third source should be used to determine whether a real adapter abstraction is justified.
