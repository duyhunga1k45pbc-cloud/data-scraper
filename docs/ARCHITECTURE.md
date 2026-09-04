# Data Scraper — Architecture Contract

## 1. Current scope: M3

M0 established the correctness loop. M1 proved a shared product core across two HTML sources. M2 falsified two assumptions: one evidence payload can produce many observations, and product identity does not always require a product URL.

M3 stress-tests **product meaning**, not acquisition scale.

Current sources:

```text
Books to Scrape  → static HTML
ScrapeMe         → WooCommerce HTML
Scrapify JS      → deterministic JSON endpoint behind JS storefront
ScrapingSandbox  → product HTML with a deterministic JSON product snapshot
```

## 2. Business goal

> Collect external product data and maintain a reliable structured current state and history without losing source-observed business meaning.

**BR-01 Acquire** — Obtain the required source evidence using the least-complex correct mechanism.

**BR-02 Structure** — Preserve required product fields under explicit representations.

**BR-03 Data state** — Explain what was observed, normalized, validated, accepted/rejected, and persisted.

**BR-04 Current trusted state** — Maintain one trusted current state per source product identity.

**BR-05 History** — Preserve accepted trusted state transitions.

**BR-06 Deliver** — Expose current state and history as structured CLI output.

**BR-07 Rich product semantics (M3)** — Preserve source-observed original/compare pricing, SKU, category cardinality, and variant-level price/availability when the source provides them.

## 3. Architecture

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

## 4. Representation boundaries

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

### ProductObservation

Source-shaped interpretation now includes optional richer fields:

```text
title_raw
price_raw
compare_at_price_raw
currency_raw
availability_raw
category_raw
categories_raw[]
sku_raw
source_record_id_raw
canonical_product_url_raw
variants_raw[]
```

Each raw variant preserves:

```text
sku_raw
price_raw
availability_raw
options_raw[]
```

### ProductNormalizedData

Typed representation:

```text
identity inputs
price
compare_at_price
currency
availability
quantity
category | null
categories[]
sku | null
variants[]
```

Variant normalization yields a stable variant key, normalized options, Decimal price, and normalized availability.

### ValidatedProduct

Only validated product data may enter state-changing logic.

### CurrentProductState

Current trusted business representation. Variant snapshots are part of the product state.

### ProductHistory

Only accepted `CREATE`/`UPDATE` transitions. A change in one validated variant is a product state change.

## 5. M3 observed semantics

ScrapingSandbox exposes a product with:

```text
price = 155.62
compareAtPrice = 206.69
sku = SKU-HEA-0001
inStock = true
category = Health
variants = 4 independently priced/stocked configurations
```

This falsifies a narrower interpretation in which one product has only one meaningful price/availability representation.

M3 therefore preserves product-level price **and** variant-level price instead of deriving one from the other.

M3 also fixes a known M1 information-loss case: ScrapeMe exposes multiple categories. The shared contract now preserves `categories[]`; legacy `category` remains only for sources that truly expose one category.

## 6. Identity

Product identity remains:

```text
source_record_id present → identity_key = "id:<source_record_id>"
otherwise                → identity_key = "url:<canonical_product_url>"
```

Variant identity is local to the product snapshot:

```text
SKU present → variant key = "sku:<sku>"
otherwise   → normalized option combination
```

M3 does not introduce cross-source or fuzzy identity resolution.

A product can still expose more than one locator. If a stable source record ID is
present, it remains the **primary identity**, but the current canonical product URL
is retained as an alternate lookup locator. Therefore URL-based delivery commands
must query the stored canonical URL rather than assume every URL-backed record uses
`url:<canonical_product_url>` as its primary `identity_key`.

## 7. Validation

Existing product rules remain:

```text
title required
price required and >= 0
currency recognized
availability recognized
quantity, when present, >= 0
OUT_OF_STOCK + positive quantity invalid
supported source + valid product identity
```

M3 adds:

```text
compare_at_price, when present, >= 0
compare_at_price, when present, must not be below current price
variant identity required
variant identity unique inside one product
variant price required and >= 0
variant availability recognized
```

No invariant states that product-level price must equal min/max variant price; the source does not support that claim.

## 8. State transition rules

### CREATE

```text
no current state + valid product
→ create state
→ append initial history
```

### NO_CHANGE

```text
same validated product semantics, including variants
→ state unchanged
→ no history
```

### UPDATE

```text
any accepted business-state difference
(including compare price, categories, SKU, or variant snapshot)
→ update current state
→ append exactly one history entry
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

**INV-08** Multiple observations from one evidence payload remain independently identifiable and traceable to that evidence.

**INV-09** Variant keys are unique within an accepted product state.

**INV-10** Accepted richer product fields must remain traceable from persisted state/history back through observation to raw evidence.

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
0004 M3 richer product semantics
```

`0004` adds to observations/current product state:

```text
compare_at_price
sku
categories[]
variants[]
```

and corresponding raw observation fields.

Variants are nested JSON snapshots, not a separate table. M3 only requires product-level current state/history. A separate variant relation is deferred until independent variant querying/history is a demonstrated requirement.

## 11. Acquisition decision in M3

ScrapingSandbox's required JSON snapshot is rendered into the product HTML itself. Therefore:

```text
httpx fetch
→ RawEvidence HTML
→ parse deterministic JSON <pre>
```

is sufficient.

Playwright remains unjustified for M3.

## 12. Acceptance criteria added by M3

```text
AC-10 compare-at price survives observation → state → history
AC-11 multiple source categories are preserved without inventing a primary category
AC-12 variants retain stable identity/options/price/availability
AC-13 a variant state change produces one product UPDATE + one history entry
AC-14 invalid/duplicate variant semantics are rejected before trusted-state mutation
AC-15 live ScrapingSandbox product reaches PostgreSQL with richer semantics intact
```

## 13. Freeze rule

```text
new mechanism only if
new business requirement
OR observed failure mode
OR current mechanism cannot preserve an invariant
```
