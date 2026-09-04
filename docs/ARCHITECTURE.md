# Data Scraper — Architecture Contract

## 1. Current scope: M5

M0 established the correctness loop. M1 proved a shared product core across two HTML sources. M2 falsified one-evidence/one-observation and URL-only identity assumptions. M3 expanded product meaning to richer e-commerce semantics. M3.1 separated primary identity from lookup locators. M4 made history semantic rather than presentation-order sensitive.

M5 stress-tests **temporal correctness**: processing order must not be allowed to rewrite trusted state backward when an older valid observation arrives after a newer one.

M5 adds no source and no persistence mechanism. It adds one explicit state decision, `STALE`, and proves that stale observations remain traceable without changing trusted state/history.

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

**BR-09 Temporal correctness (M5)** — A valid observation older than the current trusted state must not overwrite that state or append trusted history.

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
 ┌───────┼──────────┬───────────┐
 │       │          │           │
CREATE NO_CHANGE   STALE      UPDATE
 │                              │
 └──────────────┬───────────────┘
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

## 6. M5 temporal semantics

`observed_at` represents when the source evidence was observed. It is distinct from `changed_at`/transaction processing time.

For an existing trusted state:

```text
incoming.observed_at < current.observed_at
→ STALE
→ current trusted state unchanged
→ no history entry
→ observation remains persisted with state_decision = STALE
```

The temporal check occurs after identity and validation have established that the incoming object is a valid product for the same entity, but before semantic equality/update comparison. Therefore an older equivalent observation is still classified as `STALE`, not `NO_CHANGE`.

M5 deliberately covers **late-arrival ordering**, not simultaneous transaction races. Two workers that read the same old state concurrently require a later concurrency-control mechanism (for example row locking or compare-and-set) if reality demonstrates that failure mode.

## 7. Identity and locator

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

## 8. Validation

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

## 9. State transition rules

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

### STALE (M5)

```text
valid same-identity observation
+ incoming.observed_at < current.observed_at
→ persist observation as STALE
→ current trusted state unchanged
→ history unchanged
```

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

## 10. Invariants

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

**INV-12 (M5)** An observation with `observed_at` older than the current trusted state must not modify current state or append history.

**INV-13 (M6)** Concurrent transitions for an existing current-state row must be decided from the latest committed trusted state; an older concurrent observation must not overwrite a newer committed state.

## 11. Persistence

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

M4, M5, and M6 add **no migration**. Existing state/history snapshots and the string `state_decision` column already support semantic comparison and the explicit `STALE` decision.

M6 changes the PostgreSQL state-transition read for an existing product to:

```sql
SELECT ... FOR UPDATE
```

The row lock is acquired before converting the row to `CurrentProductState` and before computing the transition. A concurrent worker therefore waits, then evaluates its observation against the latest committed trusted row instead of against a stale snapshot.

`NO_CHANGE` and `STALE` observations are persisted as observations but do not append product history.

## 12. M4 observed failure and correction

Stress testing reversed the same valid variant collection while keeping every variant key/value unchanged.

Before M4:

```text
same variants, different tuple order
→ UPDATE   # false business change
```

This violated `INV-06` and the intended meaning of history.

M4 corrects state equivalence by comparing category membership, variant membership, and named variant options in canonical order **for comparison only**.

The source-shaped/raw representation is not rewritten, preserving traceability.

## 13. M6 concurrent-state failure and correction

M5 protected against a late older observation only when processing was sequential. The persistence path still had a true transaction race:

```text
trusted state = t0

worker A reads t0; incoming observed_at = t5
worker B reads t0; incoming observed_at = t3

A computes UPDATE
B computes UPDATE from the same old snapshot

A commits t5
B commits later and can overwrite with t3   # temporal regression
```

The state function itself was correct; the divergence was between the state decision's read snapshot and the database state at commit time.

M6 serializes transitions for an **existing** product row with a PostgreSQL row lock:

```text
worker A: SELECT ... FOR UPDATE → reads t0
worker B: SELECT ... FOR UPDATE → waits
worker A: UPDATE → commit t5
worker B: lock acquired → reads t5 → incoming t3 becomes STALE
```

The lock is a persistence mechanism, not a new domain state. `STALE` remains the domain decision produced by the existing M5 temporal rule. Read-only CLI lookups do not acquire the lock.

## 13. Acceptance criteria

```text
AC-16 product price change → one UPDATE with correct previous/new snapshots
AC-17 compare-at price removal → one UPDATE
AC-18 variant stock change → one product UPDATE
AC-19 variant add/remove → one product UPDATE per accepted snapshot
AC-20 variant presentation reorder only → NO_CHANGE + no history
AC-21 category presentation reorder only → NO_CHANGE + no history
AC-22 CREATE → UPDATE → equivalent replay persists observations but only meaningful history
AC-23 PostgreSQL preserves the same semantic-history contract
AC-24 older valid changed observation → STALE + current state unchanged + no history
AC-25 older equivalent observation → STALE, not NO_CHANGE
AC-26 stale observation remains persisted/traceable with `state_decision = STALE`
AC-27 PostgreSQL preserves newer trusted `observed_at`, accepted observation, and history after a stale arrival
AC-28 two concurrent observations for one existing product → newer UPDATE commits; older worker re-reads committed state and becomes STALE; no lost update or false history
```

## 14. Freeze rule

```text
new mechanism only if
new business requirement
OR observed failure mode
OR current mechanism cannot preserve an invariant
```
