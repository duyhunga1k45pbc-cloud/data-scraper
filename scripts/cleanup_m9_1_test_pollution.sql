-- One-time cleanup for the M9.1 integration-test pollution bug.
-- Scope: only the old M9 test runs that incorrectly reused source='scrapify_js'.
-- Run with psql against the data_scraper database.

BEGIN;

CREATE TEMP TABLE _m9_bad_runs ON COMMIT DROP AS
SELECT id
FROM catalog_runs
WHERE source = 'scrapify_js'
  AND scope_key = 'm9-postgres-coverage-test'
  AND run_key IN ('m9-pg-initial', 'm9-pg-partial', 'm9-pg-final');

CREATE TEMP TABLE _m9_affected_real_products ON COMMIT DROP AS
SELECT DISTINCT ph.product_id
FROM product_history ph
JOIN products p ON p.id = ph.product_id
WHERE ph.catalog_run_id IN (SELECT id FROM _m9_bad_runs)
  AND ph.decision = 'DISAPPEARED'
  AND p.source = 'scrapify_js'
  AND COALESCE(p.source_record_id, '') NOT IN ('m9-pg-a', 'm9-pg-b', 'm9-pg-c');

-- Restore presence from the state immediately before the first false disappearance.
WITH first_bad AS (
    SELECT DISTINCT ON (ph.product_id)
           ph.product_id,
           ph.previous_state
    FROM product_history ph
    WHERE ph.catalog_run_id IN (SELECT id FROM _m9_bad_runs)
      AND ph.decision = 'DISAPPEARED'
      AND ph.product_id IN (SELECT product_id FROM _m9_affected_real_products)
    ORDER BY ph.product_id, ph.id
)
UPDATE products p
SET presence_status = COALESCE(first_bad.previous_state->>'presence_status', 'ACTIVE'),
    presence_observed_at = COALESCE(
        (first_bad.previous_state->>'presence_observed_at')::timestamptz,
        p.observed_at
    )
FROM first_bad
WHERE p.id = first_bad.product_id;

-- Remove every history entry whose provenance is one of the polluted test runs.
DELETE FROM product_history
WHERE catalog_run_id IN (SELECT id FROM _m9_bad_runs);

-- Remove the three synthetic M9.1 products and their dependent history.
DELETE FROM product_history
WHERE product_id IN (
    SELECT id FROM products
    WHERE source = 'scrapify_js'
      AND source_record_id IN ('m9-pg-a', 'm9-pg-b', 'm9-pg-c')
);

DELETE FROM products
WHERE source = 'scrapify_js'
  AND source_record_id IN ('m9-pg-a', 'm9-pg-b', 'm9-pg-c');

DELETE FROM product_observations
WHERE source = 'scrapify_js'
  AND extractor_version = 'm9-pg-v1'
  AND source_record_id IN ('m9-pg-a', 'm9-pg-b', 'm9-pg-c');

DELETE FROM catalog_run_chunks
WHERE catalog_run_id IN (SELECT id FROM _m9_bad_runs);

DELETE FROM catalog_runs
WHERE id IN (SELECT id FROM _m9_bad_runs);

DELETE FROM raw_evidence
WHERE source_url LIKE 'https://scrapifydatalabs.com/m9-test/catalog%';

COMMIT;
