-- 05_index.sql
-- GIN trigram indexes + candidate search with the % operator + EXPLAIN ANALYZE.
-- Run: psql -U postgres -d namededup -f sql/05_index.sql
-- Needs: 04_normalize.sql (normalized_name filled, fn_normalize_bn_name).
--
-- How % works: a % b is true when similarity(a, b) >= pg_trgm.similarity_threshold
-- (default 0.3). A GIN gin_trgm_ops index can answer % without scanning every row.
-- pg_trgm already ignores case and punctuation, so the raw column can be indexed.

CREATE INDEX IF NOT EXISTS idx_name_record_full_name_trgm
    ON name_record USING gin (full_name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_name_record_normalized_name_trgm
    ON name_record USING gin (normalized_name gin_trgm_ops);

ANALYZE name_record;   -- fresh statistics so the planner can cost the new indexes

-- The name to search for; change it here, or run with -v q="Some Name".
\if :{?q}
\else
    \set q 'Md. Rakib Uddin Islam'
\endif

SET pg_trgm.similarity_threshold = 0.3;   -- the default, set explicitly for clarity

-- Normalize the query ONCE into psql variable :nq. Calling fn_normalize_bn_name()
-- inside the query would re-run it for every candidate row (26 ms vs 4 ms on 2.7k rows).
SELECT fn_normalize_bn_name(:'q') AS nq \gset


-- ======================================================= candidate search
-- C1. Raw names: % filters via the index, then candidates are ranked by score.
SELECT record_id, person_id, full_name,
       round(similarity(full_name, :'q')::numeric, 3) AS score
FROM name_record
WHERE full_name % :'q'
ORDER BY score DESC, record_id
LIMIT 20;

-- C2. Normalized names: search the normalized column with the normalized query.
SELECT record_id, person_id, full_name, normalized_name,
       round(similarity(normalized_name, :'nq')::numeric, 3) AS score
FROM name_record
WHERE normalized_name % :'nq'
ORDER BY score DESC, record_id
LIMIT 20;


-- ============================================================ query plans
-- Same query as C1 in both cases; only the planner settings differ.
-- Look for "Bitmap Index Scan on idx_name_record_full_name_trgm" vs "Seq Scan",
-- and compare "Execution Time" at the bottom.

-- E1. WITH the index. On a small table the planner may still pick a seq scan
-- because it is cheap; enable_seqscan = off forces the index path for the demo.
BEGIN;
SET LOCAL enable_seqscan = off;
EXPLAIN (ANALYZE, BUFFERS)
SELECT record_id, full_name, similarity(full_name, :'q') AS score
FROM name_record
WHERE full_name % :'q'
ORDER BY score DESC
LIMIT 20;
ROLLBACK;

-- E2. WITHOUT the index: switch off index and bitmap scans, forcing a seq scan
-- that computes similarity for every row.
BEGIN;
SET LOCAL enable_indexscan = off;
SET LOCAL enable_bitmapscan = off;
EXPLAIN (ANALYZE, BUFFERS)
SELECT record_id, full_name, similarity(full_name, :'q') AS score
FROM name_record
WHERE full_name % :'q'
ORDER BY score DESC
LIMIT 20;
ROLLBACK;

-- E3. Normalized column, with the index (compare with E1).
BEGIN;
SET LOCAL enable_seqscan = off;
EXPLAIN (ANALYZE, BUFFERS)
SELECT record_id, normalized_name,
       similarity(normalized_name, :'nq') AS score
FROM name_record
WHERE normalized_name % :'nq'
ORDER BY score DESC
LIMIT 20;
ROLLBACK;
