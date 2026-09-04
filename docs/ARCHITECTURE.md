# Data Scraper — Architecture Contract

## 1. Current scope: M4

M0 established the correctness loop. M1 proved a shared product core across two HTML sources. M2 falsified one-evidence/one-observation and URL-only identity assumptions. M3 expanded product meaning to richer e-commerce semantics. M3.1 separated primary identity from lookup locators.

M4 stress-tests **trusted state and history over time**.

It does not add a new source or a new persistence mechanism. Instead, controlled snapshots of the same product test whether the system distinguishes real business changes from source representation noise.

## 2. Business goal

> Collect external product data and maintain a reliable structured current state and history without losing source-observed business meaning.

**BR-01 Acquire** — Obtain required source evidence using the least-complex correct mechanism.

**BR-02 Structure** — Preserve required product fields under explicit representations.

**BR-03 Data state** — Explain what was observed, normalized, validated, accepted/rejected, and persisted.

**BR-04 Current trusted state** — Maintain one trusted current state per source product identity.

**BR-05 History** — Preserve accepted trusted state transitions.

**BR-06 Deliver** — Expose current state and history as structured CLI output.

**BR-07 Rich product semantics** — Preserve compare pricing, SKU, category cardinality, and variant-level price/availability when observed.

**BR-08 Semantic change history (M4)** — History must represent meaningful product-state changes, not ordering differences in source collections whose order has no business meaning.

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

Source-shaped interpretation. Raw collection order is preserved here because it is evidence of what the parser observed.

### ProductNormalizedData

Typed product representation including identity inputs, product pricing, category data, SKU, and variants.

### ValidatedProduct

Only validated product data may enter state-changing logic.

### CurrentProductState

Current trusted product representation.

### ProductHistory

Only accepted `CREATE`/`UPDATE` transitions. Each entry contains `previous_state` and `new_state` snapshots.

## 5. M4 change semantics

M4 controls multiple snapshots of the same ScrapingSandbox product.

The following are meaningful accepted changes:

```text
product price changes
compare_at_price appears/disappears/changes
product availability changes
category membership changes
SKU changes
variant price changes
variant availability changes
variant added
variant removed
```

The following are **not** product-state changes by themselves:

```text
same category membership in a different source order
same variants in a different source order
same named variant options in a different order
new fetched_at/observed attempt with equivalent business state
```

Therefore state comparison is semantic rather than raw tuple-order equality.

Raw observation order remains preserved for divergence tracing; only trusted-state equivalence ignores non-semantic collection order.

## 6. Identity and locator

Primary product identity remains:

```text
source_record_id present → identity_key = "id:<source_record_id>"
otherwise                → identity_key = "url:<canonical_product_url>"
```

A canonical product URL may also be an alternate locator even when the primary identity uses a source record ID.

Variant identity remains local to one product state:

```text
SKU present → variant key = "sku:<sku>"
otherwise   → normalized option combination
```

## 7. Validation

Existing rules remain:

```text
title required
price required and >= 0
currency recognized
availability recognized
quantity, when present, >= 0
OUT_OF_STOCK + positive quantity invalid
supported source + valid identity
compare_at_price, when present, >= price
variant identity required and unique
variant price required and >= 0
variant availability recognized
```

M4 does not add validation rules. It changes how two **valid** states are compared.

## 8. State transition rules

### CREATE

```text
no current state + valid product
→ create state
→ append initial history
```

### NO_CHANGE

```text
semantically equivalent validated product
→ current trusted state unchanged
→ no history
```

Equivalence ignores ordering of set-like category/variant collections while still comparing every meaningful field inside them.

### UPDATE

```text
accepted semantic difference
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

**INV-10** Accepted richer product fields remain traceable from state/history back through observation to raw evidence.

**INV-11 (M4)** Presentation-order changes in order-insensitive product collections must not create a trusted state transition.

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

Migrations remain:

```text
0001 M0 persistence
0002 M1 book → product vocabulary
0003 M2 multi-record evidence + source-record identity
0004 M3 richer product semantics
```

M4 adds **no migration**. Existing full-state history snapshots already support the required time semantics.

A `NO_CHANGE` observation is persisted as an observation but does not append product history.

## 11. M4 observed failure and correction

Stress testing reversed the same valid variant collection while keeping every variant key/value unchanged.

Before M4:

```text
same variants, different tuple order
→ UPDATE   # false business change
```

This violated `INV-06` and the intended meaning of history.

M4 corrects state equivalence by comparing category membership, variant membership, and named variant options in canonical order **for comparison only**.

The source-shaped/raw representation is not rewritten, preserving traceability.

## 12. Acceptance criteria added by M4

```text
AC-16 product price change → one UPDATE with correct previous/new snapshots
AC-17 compare-at price removal → one UPDATE
AC-18 variant stock change → one product UPDATE
AC-19 variant add/remove → one product UPDATE per accepted snapshot
AC-20 variant presentation reorder only → NO_CHANGE + no history
AC-21 category presentation reorder only → NO_CHANGE + no history
AC-22 CREATE → UPDATE → equivalent replay persists observations but only meaningful history
AC-23 PostgreSQL preserves the same semantic-history contract
```

## 13. Freeze rule

```text
new mechanism only if
new business requirement
OR observed failure mode
OR current mechanism cannot preserve an invariant
```
