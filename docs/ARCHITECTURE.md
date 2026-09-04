# Data Scraper — Architecture Contract

## 1. Current scope: M2

M0 proved one static source. M1 proved a shared `Product` state contract across two HTML sources.

M2 stress-tests the acquisition boundary with a JavaScript-rendered e-commerce storefront.

Current sources/mechanisms:

```text
Books to Scrape  → static HTML → httpx + HTML parser
ScrapeMe         → static HTML → httpx + HTML parser
Scrapify JS      → JS storefront → observed public JSON endpoint → httpx + JSON parser
```

M2 deliberately does not become a generic scraping framework.

## 2. Business goal

> Collect external product data and maintain a reliable structured current state and history.

**BR-01 — Acquire**  
Collect product data from a supported external source using the least-complex mechanism that can obtain the required evidence correctly.

**BR-02 — Structure**  
Extract and normalize required product fields into a defined schema.

**BR-03 — Data state**  
Explain which representation data is in, whether it was accepted, and why.

**BR-04 — Current trusted state**  
Maintain one trusted current state per source product identity.

**BR-05 — History**  
Preserve accepted trusted state transitions.

**BR-06 — Deliver**  
Expose current state and history as structured CLI output.

## 3. M2 observed acquisition behavior

The M2 storefront initially returns an empty product container. JavaScript then requests a JSON dataset and injects product cards.

Observed chain:

```text
GET /playground/js-rendered
      ↓
initial HTML contains no product cards
      ↓ JavaScript
GET /data/products.json
      ↓
product records
```

Therefore:

```text
browser rendering is possible
but
browser rendering is not required
```

M2 selects the deterministic public JSON endpoint directly.

This is the first concrete acquisition-selection rule:

```text
If required data is absent from initial HTML:
    inspect deterministic network evidence first
    if sufficient public endpoint exists → acquire it directly
    else → browser mechanism may be justified
```

Playwright remains deferred because M2 does not require it.

## 4. Current architecture

```text
External Source
      ↓
Acquisition
      ↓
RawEvidence
      ↓
Source Parser
      ↓
1..N ProductObservation
      ↓
ProductNormalizedData
      ↓
Validation
      ↓
ValidatedProduct
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
NormalizedData
    ↓
  REJECT
    ↓
trusted state unchanged
history unchanged
```

## 5. Representation boundaries

```text
RawEvidence
!= ProductObservation
!= ProductNormalizedData
!= ValidatedProduct
!= CurrentProductState
```

### RawEvidence

Exact acquired payload:

```text
id
source_url
fetched_at
status_code
content_type
body
body_hash
```

M2 proves cardinality is:

```text
RawEvidence 1 → N ProductObservation
```

not necessarily 1 → 1.

### ProductObservation

Source-shaped interpretation:

```text
evidence_id
extractor_version
source
source_url
observed_at

title_raw
price_raw
currency_raw
availability_raw
category_raw
source_record_id_raw
canonical_product_url_raw
```

### ProductNormalizedData

Typed representation:

```text
source
source_url
canonical_product_url | null
source_record_id | null
observed_at
title
price
currency
availability
quantity
category
```

### ValidatedProduct

Only validated product data may enter state-changing logic.

### CurrentProductState

Current trusted business representation, not simply the latest acquired value.

### ProductHistory

Only accepted `CREATE` and `UPDATE` transitions.

## 6. Identity

M1 assumed every product had a stable product URL. M2 source records expose stable IDs (`p-1001`, etc.) in one catalog payload and do not require individual product URLs.

The identity contract therefore becomes:

```text
ProductIdentity
├── source
├── canonical_product_url | null
└── source_record_id | null
```

At least one locator must exist.

Stable internal key:

```text
source_record_id present → identity_key = "id:<source_record_id>"
otherwise               → identity_key = "url:<canonical_product_url>"
```

Invariant becomes:

```text
one (source, identity_key) → at most one current trusted state
```

No fuzzy matching or cross-source entity resolution is introduced.

## 7. Normalization and validation

M2 adds `USD` because the source actually provides USD values.

Price examples:

```text
HTML source: "£51.77" → 51.77 GBP
JSON source: 129.99 + "USD" → 129.99 USD
```

Availability examples:

```text
Books:      "In stock (22 available)" → IN_STOCK, 22
ScrapeMe:   "31 in stock"              → IN_STOCK, 31
Scrapify:   true                        → IN_STOCK, quantity unknown
            false                       → OUT_OF_STOCK, quantity unknown
```

Field rules remain:

```text
title       required, non-empty
price       required, Decimal, >= 0
currency    recognized
availability recognized
quantity    if present, >= 0
```

Cross-field rule:

```text
OUT_OF_STOCK + positive quantity → invalid
```

Identity rule:

```text
source supported
AND
(source_record_id exists OR canonical product URL is valid)
```

## 8. State transitions

### CREATE

```text
no current state + valid product
→ current state created
→ initial history appended
```

### NO_CHANGE

```text
equivalent valid product
→ current state unchanged
→ no history
```

### UPDATE

```text
different valid product
→ current state updated
→ exactly one history entry appended
```

### REJECT

```text
invalid normalized data
→ current state unchanged
→ history unchanged
```

## 9. Invariants

**INV-01** Only validated + accepted data may modify trusted state.

**INV-02** Invalid/failed data must not modify current trusted state.

**INV-03** One `(source, identity_key)` has at most one current state.

**INV-04** Persisted current state must satisfy domain validation.

**INV-05** Current-state update + history append form one atomic trusted-state transaction.

**INV-06** Reprocessing equivalent state must not create duplicate trusted transitions/history.

**INV-07** History must not contain a transition trusted state never actually underwent.

**INV-08** Multiple observations derived from one evidence payload remain independently identifiable and traceable to that same evidence.

## 10. Persistence

```text
raw_evidence
      ↓ 1:N
product_observations
      ↓ accepted
   products
      ↓
product_history
```

Migrations:

```text
0001 M0 persistence
0002 M1 book → product vocabulary
0003 M2 multi-record evidence + source-record identity
```

`0003` adds:

```text
product_observations.identity_key
product_observations.source_record_id
product_observations.currency_raw
products.identity_key
products.source_record_id
products.canonical_product_url becomes optional
```

Observation uniqueness becomes:

```text
(evidence_id, extractor_version, identity_key)
```

This allows one exact JSON response to produce many independently traceable product observations.

Raw evidence still commits first. Product observations + state mutations + history are committed in the trusted-state transaction.

## 11. Divergence tracing

For any persisted product:

```text
ProductHistory
      ↑
CurrentProductState
      ↑
State Decision
      ↑
ValidatedProduct
      ↑
ProductNormalizedData
      ↑
ProductObservation
      ↑
RawEvidence
```

For M2, many products may point to the same `RawEvidence` row, which is correct because they were all observed in the same exact JSON payload.

## 12. M2 acceptance evidence

Deterministic tests must prove:

```text
one JSON evidence → multiple observations
JSON price/currency normalize to shared domain types
source_record_id creates stable product identity
one evidence can create multiple current states/history entries
reprocessing the same batch creates no duplicate effects
M0/M1 URL-identified products still work
```

Live tests additionally prove:

```text
initial JS storefront HTML has no product cards
public JSON network endpoint returns the product dataset
live JSON catalog → shared Product state
live JSON catalog → PostgreSQL
```

## 13. Current code boundaries

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
│   └── parser.py
├── scrapeme/
│   └── parser.py
├── scrapify_js/
│   ├── parser.py
│   └── service.py
├── storage/
│   ├── models.py
│   ├── repositories.py
│   └── service.py
└── main.py
```

## 14. Explicit non-goals

Do not add without new evidence:

```text
GenericEntity
plugin/source-adapter framework
fuzzy identity
cross-source entity resolution
variant model
sale/original-price model
Playwright/browser runtime
Redis
Celery
LLM extraction
alerts
dashboard
raw-evidence retention/dedup/object storage
```

## 15. Development loop

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

## 16. Freeze rule

A new mechanism is added only when at least one is true:

```text
new business requirement
OR
observed failure mode
OR
current mechanism cannot preserve an invariant
```

M2's key result is that a dynamic page did **not** automatically justify a browser. The observed network API was the smaller deterministic mechanism.
