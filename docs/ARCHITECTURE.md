# Data Scraper — Architecture Contract

## 1. Current scope: M14

M0 established the correctness loop. M1 proved a shared product core across two HTML sources. M2 falsified one-evidence/one-observation and URL-only identity assumptions. M3 expanded product meaning to richer e-commerce semantics. M3.1 separated primary identity from lookup locators. M4 made history semantic rather than presentation-order sensitive.

M5 established temporal correctness. M6 and M7 extended that rule across concurrent UPDATE and concurrent first-CREATE races.

M8 moved correctness from one entity to a catalog scope: a missing record is not evidence of disappearance without complete scope coverage.

M9 closes the coverage-claim gap: `COMPLETE` is no longer a caller-supplied assertion on the primary catalog path. It is derived from acquisition coverage evidence (ordered chunk attempts, exact RawEvidence when an HTTP response exists, continuation refs, terminal proof, and explicit failure outcomes).

M10 adds projection replay verification. The current `products` projection must be reproducible from persisted accepted semantic history plus no-history presence freshness evidence, and every replayed transition must retain valid provenance back to intact RawEvidence or an independently re-derived COMPLETE catalog proof.

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

**BR-10 Catalog completeness (M8)** — Missing records may affect trusted presence state only when the configured catalog scope is explicitly known to be complete.

**BR-11 Presence lifecycle (M8)** — Preserve `ACTIVE → DISAPPEARED → REAPPEARED` transitions without fabricating a product observation for absence.

**BR-12 Coverage proof (M9)** — A catalog run may be classified `COMPLETE` only when acquisition evidence proves traversal from the configured start reference to an explicit terminal condition with no failed/gapped chunks.

**BR-13 Projection replay verification (M10)** — Rebuild the trusted current projection from persisted semantic decisions/freshness evidence and detect any divergence from the materialized `products` table while re-verifying accepted-transition provenance.

## 3. Architecture

```text
External Source
      ↓
Catalog Acquisition
      ↓
CatalogChunkResult[]
  ├── RawEvidence when a response exists
  ├── continuation / terminal ref
  └── explicit acquisition error when no response exists
      ↓
CatalogCoverageProof
      ↓
Source Parser outputs
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
            │
     observed product
            │
   REAPPEARED when needed
            ↓
 CurrentProductState
            ↓
      ProductHistory
            ↓
           CLI

Persisted semantic ledger
            ↓
     M10 replay verifier
            ↓
compare replayed projection ↔ products
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

Current trusted product representation plus M8 presence metadata:

```text
presence_status      = ACTIVE | DISAPPEARED
presence_observed_at = latest accepted evidence about presence/absence
```

`observed_at` remains the observation time of the trusted product-field state. `presence_observed_at` may advance on a valid `NO_CHANGE` observation without creating business history.

### ProductHistory

Accepted state transitions include `CREATE`, `UPDATE`, `DISAPPEARED`, and `REAPPEARED`. Product-field transitions point to `observation_id`; an absence transition points to `catalog_run_id` because no synthetic product observation is created for absence.

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

### DISAPPEARED (M8)

```text
COMPLETE catalog run
+ existing ACTIVE product absent from observed identity set
+ catalog observed_at is not older than presence_observed_at
→ DISAPPEARED
→ append one history entry with catalog_run_id provenance
```

An INCOMPLETE catalog run never applies this transition. Repeated complete absence refreshes `presence_observed_at` but does not duplicate history.

### REAPPEARED (M8)

```text
current presence = DISAPPEARED
+ later valid direct product observation
→ REAPPEARED
→ ACTIVE
→ append history linked to product observation
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

**INV-14 (M7)** Concurrent first observations for the same `(source, identity_key)` must serialize before the CREATE decision: at most one CREATE may occur, no worker may fail merely because another worker created the identity first, and distinct observations must converge to the newest valid `observed_at`.

**INV-15 (M8)** Absence of a record may not change trusted product presence unless the catalog run is explicitly `COMPLETE`.

**INV-16 (M8)** `DISAPPEARED` history must be traceable to a complete catalog run and its raw evidence; it must not fabricate a product observation.

**INV-17 (M8)** Older catalog absence evidence must not override newer accepted presence evidence, including a newer `NO_CHANGE` observation.

**INV-18 (M9)** `COMPLETE` must be reproducible from the persisted chunk chain: traversal starts at `start_ref`, every traversed chunk succeeds, each `next_ref` equals the following `requested_ref`, and the final successful chunk has `next_ref = null`.

**INV-19 (M9)** Any fetch/HTTP/parse failure, continuation gap/cycle, or configured traversal limit makes the catalog run `INCOMPLETE`; such a run cannot produce a disappearance transition.

**INV-20 (M9)** Coverage provenance must not fabricate network evidence. A chunk with an HTTP response links to exact `RawEvidence`; a transport failure may persist with `evidence_id = null` plus an explicit error code.

**INV-21 (M10)** Replaying accepted semantic history plus no-history presence freshness evidence must reproduce the materialized current product projection and `accepted_observation_id`.

**INV-22 (M10)** Replay may trust an accepted transition only when its persisted provenance remains valid: direct transitions require an intact RawEvidence hash through `ProductObservation`; disappearance requires a re-derived COMPLETE catalog chunk proof with intact linked RawEvidence.

**INV-23 (M11)** Every persisted `(source, extractor_version)` used by observations must resolve to an explicit retained extractor runtime; verification must never fall back to a newer parser version.

**INV-24 (M11)** Re-running the recorded extractor runtime against intact RawEvidence must reproduce the persisted extraction boundary as an observation multiset.

**INV-25 (M12)** Semantic history must survive loss of the mutable `products` projection and remain sufficient to recreate an equivalent current projection and relink history by stable `(source, identity_key)`.

**INV-26 (M13)** An independently exported durable recovery bundle must be sufficient to restore a clean migrated database and recreate the same semantic `products` projection without copying `products` itself.

## 11. Persistence

```text
raw_evidence
    ↑           ↑
catalog_run_chunks
    ↓ N:1
catalog_runs
    └── derived COMPLETE absence provenance

raw_evidence
   ↓ 1:N
product_observations
      ↓ accepted provenance
product_history  ← stable semantic ledger
      ↓ nullable product_id materialization link
products         ← rebuildable current projection
```

Migrations remain:

```text
0001 M0 persistence
0002 M1 book → product vocabulary
0003 M2 multi-record evidence + source-record identity
0004 M3 richer product semantics
0005 M8 catalog completeness + product presence semantics
0006 M9 catalog coverage proof + chunk provenance
0007 M12 rebuildable projection + projection-independent history identity
```

M4, M5, M6, M7, M10, and M11 add **no migration**. Existing state/history snapshots and the string `state_decision` column already support semantic comparison and the explicit `STALE` decision.

M6 changes the PostgreSQL state-transition read for an existing product to:

```sql
SELECT ... FOR UPDATE
```

The row lock is acquired before converting the row to `CurrentProductState` and before computing the transition. A concurrent worker therefore waits, then evaluates its observation against the latest committed trusted row instead of against a stale snapshot.

`NO_CHANGE` and `STALE` observations are persisted as observations but do not append product history. M8 `NO_CHANGE` may still advance `presence_observed_at` as freshness metadata.

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

## 14. M7 concurrent-create failure and correction

M6 row locking only works when the product row already exists. A first observation has no row to lock:

```text
worker A lookup X → not found
worker B lookup X → not found

A computes CREATE
B computes CREATE

A INSERT products(X) → commit
B INSERT products(X) → unique-constraint failure
```

The unique constraint protects `INV-03`, but surfacing a database error is not the required state behavior and the losing observation would roll back instead of remaining traceable.

M7 adds a PostgreSQL **transaction-level advisory lock per product identity**, acquired before the current-state lookup:

```text
lock(source, identity_key)
        ↓
lookup current state
        ↓
CREATE / NO_CHANGE / UPDATE / STALE / REJECT
```

The identity lock exists even when no `products` row exists yet. After the first worker commits, the waiting worker acquires the same lock, re-reads current state, and produces a normal domain decision instead of a unique-constraint error.

For multi-record evidence, all identity advisory locks are deduplicated and acquired in stable sorted order before processing any record. This prevents opposite record order from creating advisory-lock deadlocks. Existing-product `SELECT ... FOR UPDATE` remains in place as the M6 row-level protection.

M7 does not introduce a lock table or a new domain state, and it requires no migration.

## 15. M8 catalog-completeness failure and correction

Before M8, a multi-record source could observe `A B C` in one run and `A B` in the next, but the system had no trustworthy basis for interpreting C's absence. A partial fetch, parser omission, or incomplete pagination could look identical to a real disappearance.

M8 introduces an explicit catalog-run contract:

```text
RawEvidence
    ↓
CatalogRun(status = COMPLETE | INCOMPLETE, source, scope_key, observed_at)
    ↓
observed identities
```

Only `COMPLETE` enables absence reconciliation. `INCOMPLETE` still processes records that were directly observed, but missing identities do not mutate trusted presence state.

A disappeared product keeps its last trusted product fields. Only presence metadata changes. The `DISAPPEARED` history entry references `catalog_run_id`, which references the exact `RawEvidence`; no fake `ProductObservation` is manufactured.

M8 also discovered that `NO_CHANGE` must still advance presence freshness. Otherwise a product seen unchanged at t10 could be falsely disappeared by a delayed complete snapshot from t5. `presence_observed_at` therefore advances independently from product-field `observed_at` and history.

M8 currently supports one whole-catalog scope per source. `scope_key` is persisted as provenance, but overlapping/multiple scope membership is intentionally not modeled until a source requires it. Catalog reconciliation for the same source/scope is serialized with a PostgreSQL transaction advisory lock.

## 16. M9 coverage-proof failure and correction

M8 protected disappearance with a `COMPLETE` gate, but the persistence API still accepted `complete=True`. That meant a buggy adapter could fetch page 1 of 5, assert `COMPLETE`, and legitimately trigger false disappearances downstream.

M9 moves completeness into the acquisition representation:

```text
start_ref = page:1

page:1 SUCCESS → next_ref=page:2
page:2 SUCCESS → next_ref=page:3
page:3 SUCCESS → next_ref=null

=> COMPLETE
```

Failure examples:

```text
page:1 SUCCESS → page:2
page:2 transport failure          => INCOMPLETE

page:1 SUCCESS → page:2
page:2 HTTP 503                   => INCOMPLETE

page:1 SUCCESS → page:2
page:2 parse failure              => INCOMPLETE

max_chunks reached with next_ref => INCOMPLETE
```

`catalog_run_chunks` persists the proof chain. `catalog_runs.evidence_id` remains as a compatibility/root anchor and is nullable for a first-page transport failure; new M9 provenance is the 1:N chunk relation.

The M8 `persist_catalog_observations(..., complete=...)` function remains only as a compatibility wrapper for replaying the M8 contract. New source paths must build a `CatalogAcquisition` and use `persist_catalog_acquisition`. Scrapify's full-catalog JSON endpoint now uses a one-chunk terminal acquisition rather than asserting `complete=True`.

## 17. M10 replay failure and correction

The first replay question was whether RawEvidence could simply be parsed again to rebuild trusted state. The existing persistence contract does not support that claim across code evolution: `extractor_version` is recorded on observations, but the executable parser implementation itself is not immutable/version-addressable. Therefore today's parser is not guaranteed to reproduce the historical interpretation of an old body.

M10 does not invent that guarantee. It defines replay at the stable semantic boundary already persisted by the system:

```text
accepted ProductHistory snapshots
+ NO_CHANGE ProductObservations that advanced presence freshness
+ repeated COMPLETE catalog absence proofs that advanced disappearance freshness
→ expected current trusted projection
```

During replay, history continuity is checked (allowing only `presence_observed_at` to advance without a history row), the latest accepted direct observation is reconstructed, RawEvidence body hashes are recomputed, and catalog completeness is independently re-derived from persisted `catalog_run_chunks`. The resulting expected state is compared field-for-field with `products`.

This makes replay useful as a drift/corruption detector without pretending to be historical raw re-extraction. A future requirement for re-running old parsers from raw bytes would require a version-addressable extractor runtime and is outside M10.

## 18. M11 version-addressable extraction failure and correction

M10 could verify semantic history and RawEvidence integrity, but it intentionally stopped before raw-body re-extraction. The reason was concrete: an observation stored `extractor_version = "scrapify-js-json-v1"`, yet no runtime resolver guaranteed that the exact v1 implementation still existed or would be selected later. Calling the current parser would make the version string descriptive metadata rather than executable provenance.

M11 introduces an extractor runtime registry keyed by both source and version:

```text
(source, extractor_version)
        ↓
ExtractorRuntime
        ├── implementation address
        └── executable extraction function
```

The implementations used by M0-M3 are moved behind explicitly versioned modules:

```text
src.extractors.books_to_scrape_v1
src.extractors.scrapeme_live_v2
src.extractors.scrapify_js_json_v1
src.extractors.scraping_sandbox_json_v1
```

The source-facing parser modules remain compatibility wrappers for the current version. Future parser changes must add a new versioned module instead of mutating the old version's behavior and must keep the historical runtime registered as long as observations reference it. Unknown versions fail closed with `EXTRACTOR_RUNTIME_NOT_FOUND`; there is no latest-version fallback.

Verification groups persisted observations by `(evidence_id, extractor_version)`, loads the exact RawEvidence, recomputes its body hash, resolves the recorded runtime, runs extraction once, and compares persisted versus re-extracted observation multisets. Multiset comparison is required because one RawEvidence may contain many products and record order is not the identity of the evidence-to-observation relation.

M0-M10 did not store the two raw identity-input fields (`source_record_id_raw`, `canonical_product_url_raw`) separately. Historical verification therefore compares the identity/locator projection that was actually persisted for those fields. All other persisted raw extraction fields, including nested variant raw data and source order, are compared directly. No migration is required for M11.

CLI:

```text
verify-extraction <source>
```

A successful report proves that the currently retained historical runtime still reproduces the persisted extraction boundary from intact RawEvidence. It is separate from M10 projection replay: M11 checks **RawEvidence → ProductObservation**, while M10 checks **persisted semantic ledger → CurrentProductState**.

## 19. M12 rebuildable-projection failure and correction

M10 proved that the current projection could be *computed* from the semantic ledger, but an operational rebuild exposed a schema contradiction. `product_history.product_id` still referenced `products.id` with `ON DELETE CASCADE`:

```text
delete products row
        ↓
ON DELETE CASCADE
        ↓
delete product_history
        ↓
rebuild evidence destroyed
```

That means `products` was not actually a disposable projection. M12 makes history identity independent from the projection:

```text
product_history
├── source             # stable domain source
├── identity_key       # stable domain identity
└── product_id         # nullable link to current materialization
                         ON DELETE SET NULL
```

The accepted semantic ledger can now be discovered by `(source, identity_key)` without reading `products`. `build_source_projection_from_ledger()` starts from an empty in-memory projection, checks history continuity/provenance, applies M10 no-history presence freshness, and produces the expected current states. M11 raw re-extraction is run before a destructive materialization so an invalid extraction chain fails closed.

The actual recovery mechanism is:

```text
verify RawEvidence → historical extraction
        ↓
build expected state from independent semantic ledger
        ↓
set product_history.product_id = null
        ↓
delete products for source
        ↓
insert fresh products rows
        ↓
relink product_history by (source, identity_key)
        ↓
replay/compare rebuilt projection
```

A source may therefore be recovered even when its `products` rows are already absent. Surrogate product IDs are not part of state meaning. During rollback-only verification on a healthy projection, the old IDs are explicitly reused so PostgreSQL sequences are not advanced by a proof that will be rolled back.

`verify-rebuild <source>` performs the real delete/recreate/relink operation inside a transaction and always rolls it back. It first runs the M10 committed-projection pre-check; any pre-existing drift fails before the destructive proof. A recovery caller can invoke the same rebuild function in an explicitly owned transaction and commit only after inspecting the report.

New invariant:

```text
INV-25 semantic history must survive projection loss and be sufficient to recreate an equivalent current projection
```


## 20. M13 clean-database disaster recovery

M12 could recover a lost `products` projection only while the rest of the database still existed. A real database-loss scenario has a harder boundary: evidence and ledger stored only inside the failed database are unavailable. M13 therefore makes the recovery input explicit instead of pretending that a clean database can reconstruct information it no longer has.

The application-level recovery bundle contains the durable chain and excludes the projection:

```text
raw_evidence
product_observations
catalog_runs
catalog_run_chunks
product_history (stable source + identity_key; product_id omitted)
        ↓ restore exact provenance ids
empty migrated database/schema
        ↓ M11 extraction verification
        ↓ M12 ledger rebuild
products
        ↓ M10 replay verification
recovered trusted state
```

RawEvidence is exported globally, not only through downstream references, so evidence that survived acquisition but failed before parsing is not silently discarded by backup selection. The bundle has a canonical SHA-256 hash; tampering fails before restore. A restore target must be empty, which prevents accidental merge semantics from being mistaken for disaster recovery.

Durable rows with integer primary keys are restored with their original ids because history/provenance references depend on them. PostgreSQL sequences are then synchronized to the restored maxima; otherwise the first post-recovery write could collide with an explicitly restored id even though the recovery itself succeeded. `products` is rebuilt with fresh materialization ids and history is relinked by stable `(source, identity_key)`.

`verify-disaster-recovery` creates a fresh PostgreSQL schema inside one rollback-only transaction, restores only the bundle, rebuilds all source projections, compares the recovered semantic projection with the source projection, and rolls the temporary schema back. This is a clean-schema proof, not a substitute for externally retaining the bundle itself.

New invariant:

```text
INV-26 clean migrated DB + intact durable recovery bundle
       → equivalent trusted semantic projection
```


## 21. Acceptance criteria

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
AC-29 two concurrent equivalent first observations for one identity → exactly one CREATE, one NO_CHANGE, one current product, and one CREATE history entry
AC-30 two concurrent distinct first observations with different `observed_at` values → no worker errors, exactly one CREATE, and final current state converges to the newest valid observation
AC-31 incomplete catalog missing an existing product → product remains ACTIVE and no disappearance history
AC-32 complete catalog missing an existing ACTIVE product → one DISAPPEARED history entry with catalog-run provenance
AC-33 repeated complete absence → no duplicate DISAPPEARED history; presence freshness advances
AC-34 later direct observation of a disappeared product → REAPPEARED + ACTIVE
AC-35 delayed older complete missing snapshot → cannot override newer presence evidence
AC-36 contiguous successful chunk chain ending at `next_ref = null` → derived COMPLETE
AC-37 fetch/HTTP/parse/limit/cycle/gap failure → derived INCOMPLETE
AC-38 incomplete persisted coverage missing an existing product → product remains ACTIVE
AC-39 complete multi-chunk proof missing an existing product → one DISAPPEARED history entry traceable through catalog_run → chunks → RawEvidence
AC-40 first-page transport failure → INCOMPLETE run/chunk persisted with no fabricated RawEvidence
AC-41 replay of CREATE/NO_CHANGE/DISAPPEARED/repeated-absence timeline → exact current state including presence freshness
AC-42 current product-row drift → replay reports CURRENT_PROJECTION_MISMATCH
AC-43 RawEvidence body tampering → replay reports RAW_EVIDENCE_HASH_MISMATCH
AC-44 disappearance catalog proof tampering → replay re-derives coverage and rejects the provenance
AC-45 PostgreSQL replay matches the committed projection and detects uncommitted projection drift without persisting the corruption
AC-46 every persisted current-source extractor version resolves to an explicit versioned runtime; unknown versions fail closed
AC-47 one-record RawEvidence re-extraction reproduces the persisted ProductObservation extraction boundary
AC-48 one-to-many RawEvidence re-extraction reproduces the persisted observation multiset independent of record ordering
AC-49 persisted extraction drift produces missing/extra re-extraction diagnostics rather than being accepted as equivalent
AC-50 PostgreSQL RawEvidence re-extraction with the recorded runtime reproduces the committed observation boundary
AC-51 deleting/detaching a source projection leaves semantic history discoverable by stable source + identity_key
AC-52 an already-empty products projection can be rebuilt to the same semantic state, including no-history presence freshness
AC-53 projection rebuild relinks every original history row to the newly materialized product identity without rewriting history ids
AC-54 invalid RawEvidence/extraction provenance fails closed before projection deletion
AC-55 PostgreSQL delete/recreate/relink verification succeeds inside a transaction and rollback restores the committed projection/history links
AC-56 recovery bundle excludes `products` while retaining all durable evidence/ledger rows and detects bundle tampering
AC-57 restoring the durable bundle into an empty database rebuilds an equivalent semantic projection and relinks history
AC-58 restore into a non-empty target fails closed rather than merging state
AC-59 PostgreSQL clean-schema disaster-recovery verification rebuilds and compares the projection, then rolls the temporary schema back
```

## 22. Freeze rule

```text
new mechanism only if
new business requirement
OR observed failure mode
OR current mechanism cannot preserve an invariant
```

## M10.1 — replay representation canonicalization

Replay compares semantic trusted state, not storage formatting. PostgreSQL
`NUMERIC(18, 2)` may read a price originally observed as `199.0` back as
`199.00`, while accepted history JSON preserves `"199.0"`. M10.1 canonicalizes
monetary decimal representations (product price, compare-at price, and variant
price) before projection comparison. Scale-only differences therefore cannot
produce a false replay drift signal.

## M14 — operational run lifecycle

M13 closes the clean-database recovery boundary. M14 starts the operational phase: a scrape execution is now durable operational state without becoming business truth.

```text
manual trigger / cron / systemd timer
        ↓
ScrapeRun(RUNNING)
        ↓
existing acquisition + M0-M13 correctness pipeline
        ↓
CatalogPersistenceResult
├── directly observed results
└── absence transitions
        ↓
ScrapeRun(SUCCEEDED | FAILED) + exact counters
```

The scheduler is only a trigger. Product truth remains in RawEvidence, observations, semantic history, and the rebuildable current projection. `scrape_runs` is therefore operational metadata and is not added to the M13 semantic recovery bundle.

M14 deliberately records an INCOMPLETE catalog as a FAILED operational run while preserving the M8/M9 rule that directly observed valid records may still be processed and missing records may not be interpreted as disappearance. A hard process crash may leave a run in RUNNING; abandoned-run detection/retry/resume is deferred to M15.

### M14 invariants

**INV-27** Every instrumented scrape execution creates exactly one identifiable ScrapeRun before acquisition/state work begins.

**INV-28** ScrapeRun status and counters describe execution outcome only; they must not override or fabricate trusted product-state decisions.

**INV-29** An INCOMPLETE catalog or execution failure must not be reported as SUCCEEDED and must not weaken M8/M9 completeness semantics.

**INV-30** A normally finalized run has exactly one terminal status, SUCCEEDED or FAILED.

### M14 acceptance criteria

```text
AC-60 successful scheduled execution -> RUNNING -> SUCCEEDED with finished_at
AC-61 counters are derived from actual direct transition results
AC-62 DISAPPEARED counting comes from explicit absence transition results, not DB time-window reconstruction
AC-63 INCOMPLETE catalog -> FAILED operational run while partial trusted processing remains governed by M8/M9
AC-64 raised execution error -> FAILED with explicit error metadata and the error is re-raised
AC-65 MANUAL and SCHEDULED triggers use the same correctness pipeline; trigger type has no authority over trusted state
```

