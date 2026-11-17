-- 02_methods_basic.sql
-- Basic similarity functions. Both return a score in [0, 1], where 1 = identical.
-- Run: psql -U postgres -d namededup -f sql/02_methods_basic.sql
-- Needs: pg_trgm (similarity) and fuzzystrmatch (levenshtein), enabled in 01_schema.sql.

-- Shared cleanup: lower-case, collapse runs of whitespace to one space, trim the ends.
-- '  Md.   RAHIM  ' -> 'md. rahim'
CREATE OR REPLACE FUNCTION fn_clean(s text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT btrim(regexp_replace(lower(s), '\s+', ' ', 'g'))
$$;

-- (1) Trigram similarity from pg_trgm: shared 3-letter chunks / all distinct chunks.
CREATE OR REPLACE FUNCTION fn_trigram_score(a text, b text) RETURNS real
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT similarity(fn_clean(a), fn_clean(b))
$$;

-- (2) Normalized Levenshtein: 1 - edits / length of the longer string.
-- Casts to numeric avoid integer division (3 / 10 = 0 in integer math).
-- Two empty strings count as identical (score 1) instead of dividing by zero.
-- Note: fuzzystrmatch's levenshtein() rejects inputs longer than 255 characters.
CREATE OR REPLACE FUNCTION fn_lev_score(a text, b text) RETURNS real
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT coalesce(
        1 - levenshtein(x, y)::numeric / nullif(greatest(length(x), length(y)), 0),
        1)::real
    FROM (SELECT fn_clean(a) AS x, fn_clean(b) AS y) AS c
$$;


-- ============================================================ examples: trigram
-- T1. Compare known spelling variants directly.
SELECT a, b, round(fn_trigram_score(a, b)::numeric, 3) AS trigram
FROM (VALUES ('Md. Rahim Uddin',     'Mohammad Rahim Uddin'),
             ('Rahman',              'Rohman'),
             ('  ABDUR   RAHMAN ',   'abdur rahman'),
             ('Rahim',               'Karim')) AS t(a, b);

-- T2. Top 5 most similar records to one search name.
SELECT record_id, person_id, full_name,
       round(fn_trigram_score(full_name, 'Mohammad Rakib Uddin Islam')::numeric, 3) AS trigram
FROM name_record
ORDER BY trigram DESC
LIMIT 5;

-- T3. Average score for true duplicates vs non-duplicates in the gold pairs.
SELECT g.is_duplicate,
       count(*)                                                   AS pairs,
       round(avg(fn_trigram_score(a.full_name, b.full_name))::numeric, 3) AS avg_trigram
FROM gold_pair g
JOIN name_record a ON a.record_id = g.record_id_a
JOIN name_record b ON b.record_id = g.record_id_b
GROUP BY g.is_duplicate;


-- ======================================================== examples: levenshtein
-- L1. Compare known spelling variants directly.
SELECT a, b, round(fn_lev_score(a, b)::numeric, 3) AS lev
FROM (VALUES ('Md. Rahim Uddin',     'Mohammad Rahim Uddin'),
             ('Islam',               'Islaam'),
             ('  ABDUR   RAHMAN ',   'abdur rahman'),
             ('Rahim',               'Karim')) AS t(a, b);

-- L2. Top 5 most similar records to one search name.
SELECT record_id, person_id, full_name,
       round(fn_lev_score(full_name, 'Mohammad Rakib Uddin Islam')::numeric, 3) AS lev
FROM name_record
ORDER BY lev DESC
LIMIT 5;

-- L3. Average score for true duplicates vs non-duplicates in the gold pairs.
SELECT g.is_duplicate,
       count(*)                                               AS pairs,
       round(avg(fn_lev_score(a.full_name, b.full_name))::numeric, 3) AS avg_lev
FROM gold_pair g
JOIN name_record a ON a.record_id = g.record_id_a
JOIN name_record b ON b.record_id = g.record_id_b
GROUP BY g.is_duplicate;
