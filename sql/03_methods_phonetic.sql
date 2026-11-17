-- 03_methods_phonetic.sql
-- Word-level phonetic similarity. Score in [0, 1]:
--   matching words / number of words in the longer name
-- Words are matched by phonetic code, ignoring order ("Rahman, Abdur" = "Abdur Rahman"),
-- and each word can be matched at most once (multiset intersection).
-- Run: psql -U postgres -d namededup -f sql/03_methods_phonetic.sql
-- Needs: fuzzystrmatch (dmetaphone, soundex).

-- Split a name into lower-case words; any non-letter (space . , ') separates words.
-- 'Md.Rahim  Uddin' -> {md, rahim, uddin};  'S.M. Rahman' -> {s, m, rahman}
-- Note: only a-z survives, so names in Bangla script produce no words.
CREATE OR REPLACE FUNCTION fn_words(s text) RETURNS SETOF text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT w
    FROM regexp_split_to_table(btrim(regexp_replace(lower(s), '[^a-z]+', ' ', 'g')), ' ') AS w
    WHERE w <> ''
$$;

-- Shared core: algo = 'dmetaphone' or 'soundex'.
CREATE OR REPLACE FUNCTION fn_word_code_ratio(a text, b text, algo text) RETURNS real
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    WITH ca AS (
        SELECT CASE algo WHEN 'soundex' THEN soundex(w) ELSE dmetaphone(w) END AS code,
               count(*) AS n
        FROM fn_words(a) AS w GROUP BY 1
    ), cb AS (
        SELECT CASE algo WHEN 'soundex' THEN soundex(w) ELSE dmetaphone(w) END AS code,
               count(*) AS n
        FROM fn_words(b) AS w GROUP BY 1
    )
    SELECT CASE WHEN greatest(na, nb) = 0 THEN 1            -- both empty: identical
                ELSE matched::numeric / greatest(na, nb) END::real
    FROM (SELECT coalesce(sum(least(ca.n, cb.n)), 0) AS matched
          FROM ca JOIN cb USING (code)) AS m,
         (SELECT coalesce(sum(n), 0) AS na FROM ca) AS x,
         (SELECT coalesce(sum(n), 0) AS nb FROM cb) AS y
$$;

-- Main phonetic method: Double Metaphone (primary code) per word.
CREATE OR REPLACE FUNCTION fn_phonetic_score(a text, b text) RETURNS real
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT fn_word_code_ratio(a, b, 'dmetaphone')
$$;

-- Comparison method: Soundex per word.
CREATE OR REPLACE FUNCTION fn_soundex_score(a text, b text) RETURNS real
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT fn_word_code_ratio(a, b, 'soundex')
$$;


-- ================================================================ examples
-- P1. Known variants: what each algorithm catches and misses.
SELECT a, b,
       round(fn_phonetic_score(a, b)::numeric, 3) AS dmetaphone,
       round(fn_soundex_score(a, b)::numeric, 3)  AS soundex
FROM (VALUES ('Abdur Rahman',        'Abdur Rohman'),       -- vowel change
             ('Rahman, Abdur',       'Abdur Rahman'),       -- word order
             ('Md. Rahim Uddin',     'Mohammad Rahim Uddin'), -- prefix (needs normalization)
             ('Shafiq Islam',        'Safiq Islaam'),       -- sh/s + doubled letter
             ('Rahim Khan',          'Karim Khan')) AS t(a, b);  -- different people

-- P2. Top 5 most similar records to one search name.
SELECT record_id, person_id, full_name,
       round(fn_phonetic_score(full_name, 'Mohammad Rakib Uddin Islam')::numeric, 3) AS dmetaphone,
       round(fn_soundex_score(full_name, 'Mohammad Rakib Uddin Islam')::numeric, 3)  AS soundex
FROM name_record
ORDER BY dmetaphone DESC, soundex DESC
LIMIT 5;

-- P3. Average score for true duplicates vs non-duplicates in the gold pairs.
SELECT g.is_duplicate,
       count(*) AS pairs,
       round(avg(fn_phonetic_score(a.full_name, b.full_name))::numeric, 3) AS avg_dmetaphone,
       round(avg(fn_soundex_score(a.full_name, b.full_name))::numeric, 3)  AS avg_soundex
FROM gold_pair g
JOIN name_record a ON a.record_id = g.record_id_a
JOIN name_record b ON b.record_id = g.record_id_b
GROUP BY g.is_duplicate;
