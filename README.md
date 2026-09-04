# Data Scraper

## Goal

Collect external product data and maintain a reliable structured current state and history.

Current milestones:

- **M0 — Books to Scrape:** one static HTML source, end-to-end correctness loop.
- **M1 — ScrapeMe:** second HTML e-commerce source, shared `Product` state contract.
- **M2 — Scrapify JS:** one evidence payload can contain many product records and stable source IDs can be the best identity.
- **M3 — ScrapingSandbox:** richer product semantics: compare-at pricing, SKU, categories, variants, and variant stock/price.
- **M3.1 — identity vs locator:** URL lookup is separated from primary product identity.
- **M4 — semantic change history:** trusted history records meaningful product changes while ignoring source presentation-order noise.
- **M5 — temporal correctness:** a valid observation older than the current trusted state is traced as `STALE` and cannot move state/history backward in time.
- **M6 — concurrent update correctness:** existing-product transitions are serialized from the latest committed row.
- **M7 — concurrent CREATE correctness:** first observations serialize by product identity before deciding CREATE.
- **M8 — catalog completeness + disappearance semantics:** missing records change presence state only when the configured catalog scope is COMPLETE.
- **M9 — coverage proof:** COMPLETE is derived from persisted acquisition chunks/continuation evidence instead of being asserted by the caller.
- **M10 — projection replay verification:** rebuild the trusted current projection from persisted semantic history/freshness evidence, verify provenance, and detect drift.
- **M11 — version-addressable raw re-extraction:** retain historical extractor implementations by version and verify persisted observations by re-running the recorded runtime against RawEvidence.
- **M12 — empty-projection recovery:** make semantic history independent from `products`, rebuild a source projection from the ledger, relink history, and verify the destructive cycle inside a rollback-only transaction.
- **M13 — clean-database disaster recovery:** export durable evidence/ledger state without `products`, restore it into an empty schema/database, rebuild all projections, and compare the recovered semantic state with the source.



## M13 finding

M12 proved that `products` can be deleted and rebuilt, but that is not whole-database disaster recovery. If the database itself is lost, RawEvidence, observations, catalog coverage proof, and semantic history are lost with it unless they exist outside the failed database. M13 therefore introduces an application-level recovery bundle that deliberately excludes the rebuildable projection:

```text
Recovery bundle
├── raw_evidence                 # includes orphan/parser-failure evidence
├── product_observations         # persisted historical interpretation
├── catalog_runs
├── catalog_run_chunks           # persisted completeness proof
└── product_history              # semantic ledger, product_id omitted

products                         # NOT exported
```

A restore target must already be migrated and empty. Exact durable primary keys are restored so provenance references remain valid, PostgreSQL sequences are advanced after explicit-ID restore, then every source projection is rebuilt from the recovered ledger and re-verified with M10/M11 semantics. A non-empty target fails closed.

Export/restore:

```bash
python -m src.main export-recovery recovery.json

# On a fresh migrated database:
python -m src.main --database-url "$RECOVERY_DATABASE_URL" \
  restore-recovery recovery.json
```

Rollback-only disaster-recovery proof on PostgreSQL:

```bash
python -m src.main verify-disaster-recovery
```

The verifier creates a fresh temporary PostgreSQL schema, restores only the durable bundle, rebuilds `products`, compares the recovered semantic projection with the committed source projection, then rolls the entire schema back. No migration is added in M13.


## M12 finding

M10 could compute the expected projection, but the schema still made actual recovery impossible: `product_history.product_id` pointed to `products.id` with `ON DELETE CASCADE`. Deleting a projection row therefore deleted the semantic history needed to rebuild it. A projection that destroys its own ledger when removed is not truly rebuildable.

M12 moves stable identity into the ledger itself:

```text
product_history
├── source
├── identity_key
└── product_id  # nullable materialization link only
```

`product_id` now uses `ON DELETE SET NULL`; `(source, identity_key)` is the durable history identity. The rebuild path therefore starts with no trusted `products` state:

```text
RawEvidence --M11 re-extraction verification--> persisted observations
                                      ↓
product_history + catalog completeness/freshness evidence
                                      ↓
                         ledger-only expected projection
                                      ↓
                    detach history from product surrogate ids
                                      ↓
                              delete products projection
                                      ↓
                           materialize fresh products rows
                                      ↓
                         relink original history by identity
```

`build_source_projection_from_ledger()` never reads `products`. `rebuild_source_projection_in_place()` can therefore recover a source whose projection is already empty. It fails closed before deleting anything when raw extraction or ledger provenance is invalid.

For routine proof, use the rollback-only CLI:

```bash
python -m src.main verify-rebuild scrapify_js
```

The verifier first checks the committed projection, runs the real delete/recreate/relink path, verifies the rebuilt state, then rolls the transaction back. When the original projection exists, M12 reuses its surrogate IDs during verification so PostgreSQL sequences are not consumed by a rollback-only proof.


## M11 finding

M10 identified a real boundary: storing only `extractor_version` did not make that version executable. M11 turns the version into an addressable runtime contract. Historical implementations live in versioned modules and are registered by `(source, extractor_version)`:

```text
RawEvidence
    +
(source, extractor_version)
    ↓
ExtractorRuntime registry
    ↓
versioned extractor implementation
    ↓
re-extracted ProductObservation multiset
    ↓ compare
persisted ProductObservation rows
```

The registry never falls back from an unknown historical version to the latest parser. A future extraction change must add a new versioned implementation and move the source's compatibility wrapper to that new version while retaining the old module for replay.

M11 verifies one evidence payload once per recorded extractor version and compares the full persisted extraction surface as a multiset, so both 1:1 and 1:N evidence cardinality are covered. Raw product fields, categories, variants, source/version/timestamps, and the persisted identity/locator projection must reproduce. A changed persisted observation, missing runtime, parser failure, extra/missing re-extracted record, or RawEvidence hash mismatch makes verification diverge.

M0-M10 did not persist `source_record_id_raw` and `canonical_product_url_raw` as separate raw columns; they were persisted as their normalized identity/locator projection. M11 therefore verifies that historical projection for those two fields while all other persisted extraction fields are compared directly.

Run it with:

```bash
python -m src.main verify-extraction scrapify_js
```

A consistent source exits `0`; divergence exits `1`. M11 requires no schema migration.

## M10.1 replay representation fix

PostgreSQL `NUMERIC(18, 2)` materializes values such as `199.0` as `199.00`, while JSON history preserves the original decimal scale. Replay now canonicalizes monetary Decimal representations before comparison, so scale-only representation differences do not become false `CURRENT_PROJECTION_MISMATCH` results. Mismatch diagnostics also name the differing projection fields.

## M10 finding

Raw response bytes alone are not yet a deterministic historical replay contract: the project does not persist an immutable/version-addressable extractor runtime. Re-running today's parser against yesterday's body could silently change interpretation after parser code evolves.

M10 therefore replays the **persisted semantic ledger** that already records the accepted interpretation, while independently re-checking its evidence chain:

```text
ProductHistory accepted snapshots
        +
NO_CHANGE presence observations
        +
repeated COMPLETE absence proofs
        ↓
replayed trusted projection
        ↓ compare
current products table
```

For every accepted transition M10 also verifies provenance:

```text
CREATE / UPDATE / REAPPEARED
→ ProductObservation
→ RawEvidence body hash

DISAPPEARED
→ CatalogRun
→ re-derived COMPLETE chunk chain
→ RawEvidence body hashes
```

This catches projection drift, broken history continuity, tampered raw evidence, and disappearance history whose persisted chunk chain no longer proves completeness. M10 deliberately does **not** claim raw-body re-extraction across parser versions; that would require a future version-addressable extractor mechanism.


## M9 finding

M8 made disappearance conditional on a `COMPLETE` catalog run, but `COMPLETE` itself was still a caller-supplied claim. M9 moves that claim behind an acquisition proof:

```text
configured start_ref
       ↓
chunk 0 SUCCESS --next_ref--> chunk 1 SUCCESS
       ↓                         ↓
 RawEvidence                 RawEvidence
                                 ↓
                         next_ref = null
                                 ↓
                              COMPLETE
```

Any transport failure, HTTP error, parser failure, pagination cycle, traversal limit, or broken continuation chain produces `INCOMPLETE`. Direct observations from successful chunks are still processed, but missing identities cannot become `DISAPPEARED`.

M9 also persists `catalog_run_chunks`, so the completeness decision is auditable. A transport failure has no HTTP response and therefore no fabricated `RawEvidence`; the failed chunk records its error directly.

## M8 finding

A product missing from one acquisition result is not automatically evidence that the product disappeared. M8 makes catalog completeness explicit:

```text
INCOMPLETE catalog run
A B [C missing]
→ C remains ACTIVE

COMPLETE catalog run
A B [C missing]
→ C becomes DISAPPEARED
→ one history transition with catalog-run provenance
```

If C is directly observed later, it becomes `REAPPEARED`. Repeated complete runs that still omit C refresh presence evidence but do not create duplicate disappearance history.

M8 also separates business-state observation time from **presence freshness**. A newer `NO_CHANGE` observation advances `presence_observed_at`, so a delayed older catalog snapshot cannot falsely disappear a product seen more recently.

## M5 finding

A valid observation can arrive late. Processing order is therefore not the same thing as observation time.

M5 adds an explicit temporal state decision:

```text
current observed_at = 10:05
late observation    = 10:00
        ↓
STALE
        ↓
current state unchanged
history unchanged
observation still persisted for traceability
```

The ordering rule uses `observed_at`, not transaction/processing time. M5 intentionally does **not** claim to solve simultaneous database races between concurrent workers; it establishes the temporal rule that a later concurrency mechanism must preserve.

## M4 finding

The M3 state comparator treated variant tuple order as business meaning. Reversing the same variant records therefore produced a false `UPDATE` even though the product had not changed.

M4 changes the state comparison contract:

```text
meaningful product change
→ UPDATE + history

same categories/variants in a different source order
→ NO_CHANGE
→ no history
```

Raw observations still preserve source order for traceability. Only the **trusted-state comparison** treats category membership, variant membership, and named variant-option order as order-insensitive semantics.

## Core flow

```text
External Source
      ↓
Acquisition
      ↓
Catalog Acquisition
      ↓
0..N RawEvidence + chunk outcomes
      ↓
CatalogCoverageProof
      ↓
CatalogRun (derived COMPLETE / INCOMPLETE)
      ↓
1..N ProductObservation
      ↓
Normalize
      ↓
Validate
      ↓
State Transition
      ↓
CurrentProductState
      ↓
ProductHistory
      ↓
CLI
```

Core rule:

> Only validated and accepted product data may change trusted persisted state.

M4 strengthens that rule:

> History records business-state changes, not source presentation-order changes.

M5 adds:

> An older valid observation may be retained as evidence/observation, but it must not overwrite a newer trusted state.

M6 adds:

> Concurrent transitions for an existing product must be decided from the latest committed state.

M7 adds:

> Concurrent first observations for the same identity must serialize before CREATE, so one worker creates and the others re-evaluate against that committed state instead of failing on uniqueness.

M8 adds:

> Absence may change trusted presence state only when the configured catalog scope is complete.

M9 strengthens it:

> Completeness is a derived claim backed by persisted acquisition chunks, not a caller-supplied boolean.

M10 adds:

> The current trusted projection must be reproducible from persisted semantic decisions and freshness evidence, with every accepted transition still provably linked to intact source evidence.

M11 adds:

> A persisted extractor version must resolve to an explicit retained runtime, and that runtime must reproduce the persisted extraction boundary from RawEvidence.

M12 adds:

> The semantic ledger must survive removal of the mutable `products` projection and must be sufficient to materialize and relink an equivalent projection from empty state.

M13 adds:

> A clean migrated database must be recoverable from an independently exported durable evidence/ledger bundle without copying the `products` projection.

## Current sources

```text
Books to Scrape   → static HTML
ScrapeMe          → static WooCommerce HTML
Scrapify JS       → public JSON endpoint observed behind JS storefront
ScrapingSandbox   → product HTML containing deterministic JSON preview
```

No browser automation is required by the current evidence paths.

## Change semantics covered by M4

The deterministic M4 replay tests exercise the same ScrapingSandbox product across controlled snapshots:

```text
product price changed         → UPDATE
compare-at price removed      → UPDATE
variant stock changed         → UPDATE
variant added/removed         → UPDATE
variant order only changed    → NO_CHANGE
category order only changed   → NO_CHANGE
same changed snapshot replayed→ NO_CHANGE
```

A history entry stores both `previous_state` and `new_state`, so each accepted transition remains explainable.

## Identity

Products can use either:

```text
source + canonical_product_url
```

or:

```text
source + source_record_id
```

A stable source record ID remains the primary identity when available. A canonical URL may still be used as an alternate lookup locator.

Variants remain nested inside the parent product state and use a stable local key, preferring SKU when available.

## Persistence

```text
raw_evidence
   ↑             ↑
catalog_run_chunks
   ↓ N:1
catalog_runs
   └── derived COMPLETE absence provenance

raw_evidence
   ↓ 1:N
product_observations
      ↓ accepted state decision
product_history  ← stable semantic ledger (`source`, `identity_key`)
      ↓ nullable materialization link
products         ← rebuildable current projection
```

M4 through M7 require **no schema migration**. M8 adds migration `0005_m8_catalog_completeness`. M9 adds `0006_m9_catalog_coverage_proof`, which persists catalog run keys/start refs and the 1:N `catalog_run_chunks` proof relation. M12 adds `0007_m12_rebuildable_projection`, which decouples semantic history identity from the mutable `products` surrogate row. M13 requires no schema migration.

## Local PostgreSQL

```bash
docker compose up -d postgres
export DATABASE_URL='postgresql+psycopg://data_scraper:data_scraper@localhost:5433/data_scraper'
alembic upgrade head
```

## Tests

Deterministic suite:

```bash
pytest -q
```

M4 deterministic semantic-history tests:

```bash
pytest -q \
  tests/acceptance/test_m4_semantic_change_history.py \
  tests/acceptance/test_m4_semantic_change_persistence.py
```

M4 PostgreSQL change-over-time test:

```bash
RUN_POSTGRES=1 \
pytest -q tests/integration/test_m4_postgres_change_history.py
```

M5 temporal correctness tests:

```bash
pytest -q \
  tests/acceptance/test_m5_temporal_state.py \
  tests/acceptance/test_m5_temporal_persistence.py

RUN_POSTGRES=1 \
pytest -q tests/integration/test_m5_postgres_temporal_state.py
```

M6 concurrent-state correctness (PostgreSQL row-lock proof):

```bash
RUN_POSTGRES=1 \
pytest -q tests/integration/test_m6_postgres_concurrent_state.py
```

M6 protects an existing product from a stale concurrent worker overwriting a newer commit by locking the current row before the transition decision is computed.

M7 concurrent-first-observation correctness (PostgreSQL identity-lock proof):

```bash
RUN_POSTGRES=1 \
pytest -q tests/integration/test_m7_postgres_concurrent_create.py
```

M7 uses a PostgreSQL transaction-level advisory lock keyed by `(source, identity_key)` before the current-state lookup. This closes the missing-row race that `SELECT ... FOR UPDATE` cannot lock. Multi-record identities are locked in stable order.

M8 catalog completeness tests:

```bash
pytest -q tests/acceptance/test_m8_catalog_completeness.py

RUN_POSTGRES=1 \
pytest -q tests/integration/test_m8_postgres_catalog_completeness.py
```

The live Scrapify catalog path is marked COMPLETE only after its deterministic full-catalog JSON payload parses successfully. M8 currently models one whole-catalog scope per source; it does not yet model overlapping catalog scopes.

M9 coverage-proof tests:

```bash
pytest -q \
  tests/unit/test_m9_catalog_coverage.py \
  tests/acceptance/test_m9_catalog_coverage_persistence.py

RUN_POSTGRES=1 \
pytest -q tests/integration/test_m9_postgres_catalog_coverage.py
```

The live Scrapify full-payload path now uses the same M9 proof model as a one-chunk terminal catalog. Paginated sources use `acquire_paginated_catalog`, where continuation/terminal evidence derives completeness.

M10 replay verification tests:

```bash
pytest -q \
  tests/acceptance/test_m10_projection_replay.py \
  tests/unit/test_m10_replay_cli.py

RUN_POSTGRES=1 \
pytest -q tests/integration/test_m10_postgres_projection_replay.py
```

M11 version-addressable raw re-extraction tests:

```bash
pytest -q \
  tests/unit/test_m11_extractor_registry.py \
  tests/acceptance/test_m11_raw_reextraction.py \
  tests/unit/test_m11_reextraction_cli.py

RUN_POSTGRES=1 \
pytest -q tests/integration/test_m11_postgres_raw_reextraction.py
```

M12 empty-projection rebuild tests:

```bash
pytest -q \
  tests/acceptance/test_m12_projection_rebuild.py \
  tests/unit/test_m12_rebuild_cli.py

RUN_POSTGRES=1 \
pytest -q tests/integration/test_m12_postgres_projection_rebuild.py
```

M13 clean-database disaster-recovery tests:

```bash
pytest -q tests/acceptance/test_m13_disaster_recovery.py

RUN_POSTGRES=1 \
pytest -q tests/integration/test_m13_postgres_disaster_recovery.py
```

Full integration suite, including live sources:

```bash
RUN_LIVE=1 RUN_POSTGRES=1 pytest -q tests/integration
```

## CLI

Scrape a product:

```bash
python -m src.main scrape \
  https://scrapingsandbox.com/product/1
```

Inspect current state/history:

```bash
python -m src.main show \
  https://scrapingsandbox.com/product/1

python -m src.main history \
  https://scrapingsandbox.com/product/1
```

M2 catalog commands remain available:

```bash
python -m src.main scrape-catalog scrapify-js
python -m src.main show-record scrapify_js p-1001
python -m src.main history-record scrapify_js p-1001
```

M10 can independently replay and verify one source projection:

```bash
python -m src.main verify-replay scrapify_js
```

Exit code `0` means `CONSISTENT`; exit code `1` means replay found projection/provenance divergence.

M11 can independently verify historical extraction from RawEvidence:

```bash
python -m src.main verify-extraction scrapify_js
```

Exit code `0` means every recorded extractor runtime reproduced its persisted observations; exit code `1` means extraction provenance diverged.

M12 can prove a real projection delete/recreate/relink cycle without committing it:

```bash
python -m src.main verify-rebuild scrapify_js
```

Exit code `0` means the independent ledger rebuilt an equivalent projection and the transaction was rolled back; exit code `1` means the pre-check, extraction chain, ledger, or rebuilt projection diverged.

M13 can export durable recovery state, restore it into an empty migrated database, and prove a full clean-schema recovery:

```bash
python -m src.main export-recovery recovery.json
python -m src.main --database-url "$RECOVERY_DATABASE_URL" restore-recovery recovery.json
python -m src.main verify-disaster-recovery
```

`verify-disaster-recovery` never commits the temporary recovery schema.

## Architecture contract

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Freeze rule

A new mechanism is added only when required by:

```text
new business requirement
OR
observed failure mode
OR
current mechanism cannot preserve an invariant
```

## M14 finding — operational run lifecycle

M0-M13 made the scraper correct when invoked, but execution itself was implicit. M14 introduces `scrape_runs` as operational metadata and an explicit result envelope from catalog persistence.

```text
trigger
  ↓
ScrapeRun RUNNING
  ↓
existing acquisition / evidence / semantic-state pipeline
  ↓
CatalogPersistenceResult
  ↓
ScrapeRun SUCCEEDED or FAILED + counters
```

`CatalogPersistenceResult` contains both directly observed product results and absence transitions, so `DISAPPEARED` is counted from the actual transition rather than reconstructed later from database timestamps.

A COMPLETE acquisition can finish SUCCEEDED. An INCOMPLETE acquisition is recorded as FAILED operationally, while the existing M8/M9 rules still allow safe processing of directly observed records and forbid false disappearance. Exceptions finalize FAILED and are re-raised. A process crash can still leave RUNNING; retry/resume/reaping is intentionally M15.

M14 does not embed a scheduler framework. Cron/systemd may trigger the same run service with `trigger_type=SCHEDULED`; scheduling never becomes source of truth.

## M15 finding — abandoned execution recovery and retry

M14 exposed an operational state that normal exception handling cannot close: `RUNNING` survives if the process is terminated before its finalizer executes. M15 adds an explicit operator recovery step and retry lineage without changing product truth.

```text
old RUNNING
  ↓ operator cutoff
FAILED (RUN_ABANDONED, accounting_complete=false)
  ↓ retry
new run (retry_of_run_id=<parent>, attempt=<parent+1>)
```

`accounting_complete` is important: a hard crash or raised operation may have partial durable effects before a complete `CatalogPersistenceResult` exists. Such a run must not report zero counters as proof that zero work occurred. Normal COMPLETE/INCOMPLETE finalization has complete accounting; crash/exception recovery does not.

Retry is whole-run retry. M15 intentionally does not persist an acquisition cursor or resume at page/chunk N. The current M0-M13 idempotence and temporal semantics make restarting safe for trusted state; chunk-level resume is deferred until a real source makes restart cost or behavior unacceptable.

## M16 finding — operational observability without new truth

M16 adds structured run events and durable run metrics without changing product semantics or adding another database table.

```text
ScrapeRun
  ├── JSON event: scrape_run_started / scrape_run_finished / scrape_run_abandoned
  └── durable metrics snapshot from scrape_runs
```

A logging sink is best effort and cannot fail the scraper. Events contain operational metadata only; they do not log raw response bodies, product snapshots, or stored error messages. Metrics sum product-work counters only where `accounting_complete=true`.

Inspect metrics directly:

```bash
python -m src.observability.cli --database-url "$DATABASE_URL" run-metrics
python -m src.observability.cli --database-url "$DATABASE_URL" run-metrics --source scrapify_js --since-hours 24
```

M16 intentionally does not install Prometheus/OpenTelemetry/Grafana. The observability boundary is now explicit; external delivery can be added later without becoming a source of product truth.

