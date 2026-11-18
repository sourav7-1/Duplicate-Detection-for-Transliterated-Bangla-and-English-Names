-- 04_normalize.sql
-- Bangla-name normalization driven by a rule table, plus normalized versions of the
-- trigram and Levenshtein scores.
-- Run: psql -U postgres -d namededup -f sql/04_normalize.sql
-- Needs: 02_methods_basic.sql (fn_trigram_score, fn_lev_score).
-- Safe to re-run: existing rules (including ones you added) are kept.

-- ------------------------------------------------------------------ rule table
-- rule_type 'pattern' = regex replaced anywhere in the string
-- rule_type 'word'    = whole word only ('md' matches "md rahim", not "ahmed")
-- Rules run in apply_order; set is_active = false to switch one off (RQ2 ablation).
CREATE TABLE IF NOT EXISTS name_variant_rule (
    rule_id      INTEGER      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rule_group   VARCHAR(30)  NOT NULL,
    rule_type    VARCHAR(10)  NOT NULL CHECK (rule_type IN ('pattern', 'word')),
    pattern      VARCHAR(60)  NOT NULL CHECK (pattern <> ''),
    replacement  VARCHAR(60)  NOT NULL,          -- '' deletes the match
    apply_order  SMALLINT     NOT NULL CHECK (apply_order > 0),
    is_active    BOOLEAN      NOT NULL DEFAULT TRUE,
    UNIQUE (rule_type, pattern)
);

INSERT INTO name_variant_rule (rule_group, rule_type, pattern, replacement, apply_order) VALUES
    -- 1. punctuation -> space, so "Md.Rahim" still splits into two words
    ('punctuation', 'pattern', '[.-]',      ' ',         10),
    ('punctuation', 'pattern', ',',         ' ',         10),   -- extra: "Rahman, Abdur"
    -- 2. whole-word prefixes, honorifics and titles (before letter rules change them)
    ('prefix',      'word',    'md',        'muhammad',  20),
    ('prefix',      'word',    'mohd',      'muhammad',  20),
    ('prefix',      'word',    'mohammad',  'muhammad',  20),
    ('prefix',      'word',    'mohammed',  'muhammad',  20),
    ('prefix',      'word',    'muhammad',  'muhammad',  20),
    ('prefix',      'word',    'abdur',     'abdul',     20),
    ('prefix',      'word',    'abdul',     'abdul',     20),
    ('prefix',      'word',    'sk',        'sheikh',    20),
    ('prefix',      'word',    'sheikh',    'sheikh',    20),
    ('prefix',      'word',    'ch',        'chowdhury', 20),
    ('prefix',      'word',    'chowdhury', 'chowdhury', 20),
    ('prefix',      'word',    'choudhury', 'chowdhury', 20),
    ('prefix',      'word',    'mst',       'mosammat',  20),   -- extra: female prefixes
    ('prefix',      'word',    'most',      'mosammat',  20),   --   used by the generator
    ('prefix',      'word',    'musammat',  'mosammat',  20),
    ('title',       'word',    'dr',        '',          20),
    ('title',       'word',    'engr',      '',          20),
    -- 3. letter-level spelling variants
    ('double_vowel', 'pattern', 'aa',       'a',         30),
    ('double_vowel', 'pattern', 'ee',       'i',         30),
    ('double_vowel', 'pattern', 'oo',       'u',         30),
    ('consonant',   'pattern', 'ph',        'f',         40),
    ('consonant',   'pattern', 'z',         'j',         40),
    ('consonant',   'pattern', 'sh',        's',         40),
    -- 4. doubled consonants -> one ("Rassel" -> rasel, "Rahmman" -> rahman). Runs last so
    --    it also catches doubles created above (z -> j, sh -> s). Also collapses the
    --    canonical forms: muhammad -> muhamad, hossain -> hosain, uddin -> udin.
    ('double_consonant', 'pattern', '([bcdfghjklmnpqrstvwxyz])\1', '\1', 50)
ON CONFLICT (rule_type, pattern) DO NOTHING;

-- ------------------------------------------------------------ normalizer
-- STABLE, not IMMUTABLE: the result depends on the rule table, so it cannot back an
-- expression index. Store the output in name_record.normalized_name instead (below).
CREATE OR REPLACE FUNCTION fn_normalize_bn_name(name text) RETURNS text
LANGUAGE plpgsql STABLE STRICT PARALLEL SAFE AS $$
DECLARE
    s text := lower(name);
    r record;
BEGIN
    FOR r IN SELECT rule_type, pattern, replacement
             FROM name_variant_rule
             WHERE is_active
             ORDER BY apply_order, rule_id
    LOOP
        IF r.rule_type = 'word' THEN
            s := regexp_replace(s, '\m' || r.pattern || '\M', r.replacement, 'g');
        ELSE
            s := regexp_replace(s, r.pattern, r.replacement, 'g');
        END IF;
    END LOOP;
    RETURN btrim(regexp_replace(s, '\s+', ' ', 'g'));
END
$$;

-- ------------------------------------------------- normalized score versions
-- Handy for ad-hoc comparisons. For bulk evaluation, compare the stored
-- normalized_name columns with fn_trigram_score / fn_lev_score instead: it is much
-- faster than re-running the rule loop twice per pair.
CREATE OR REPLACE FUNCTION fn_trigram_score_norm(a text, b text) RETURNS real
LANGUAGE sql STABLE STRICT PARALLEL SAFE AS $$
    SELECT fn_trigram_score(fn_normalize_bn_name(a), fn_normalize_bn_name(b))
$$;

CREATE OR REPLACE FUNCTION fn_lev_score_norm(a text, b text) RETURNS real
LANGUAGE sql STABLE STRICT PARALLEL SAFE AS $$
    SELECT fn_lev_score(fn_normalize_bn_name(a), fn_normalize_bn_name(b))
$$;

-- ---------------------------------------------------- common-token removal
-- Very frequent name words make unrelated people look similar ("Md. Munir Rahman" vs
-- "Mohammad Rakib Rahman" share muhammad + rahman). This drops them as whole words.
-- Apply it to NORMALIZED names, where every Md/Mohd/Mohammed spelling is already
-- "muhamad" (doubled consonants collapsed); the raw spellings are listed too, so
-- fn_strip_common_tokens(fn_normalize_bn_name(x)) and plain lower-case input both work. If nothing is left (e.g. "Md. Rahman"), the input is returned unchanged
-- so the name can still be compared.
CREATE OR REPLACE FUNCTION fn_strip_common_tokens(s text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
    SELECT coalesce(
        nullif(btrim(regexp_replace(
            regexp_replace(lower(s),
                '\m(muhammad|muhamad|md|rahman|hossain|hosain|islam|ahmed|akter|khatun)\M', '', 'g'),
            '\s+', ' ', 'g')), ''),
        lower(s))
$$;

-- Fill the stored column. Re-run this after adding or switching off rules.
UPDATE name_record SET normalized_name = fn_normalize_bn_name(full_name);


-- ================================================================ examples
-- N1. What the normalizer does to typical variants.
SELECT raw, fn_normalize_bn_name(raw) AS normalized
FROM (VALUES ('Md. Abdur Rahman'), ('MOHAMMED Abdul Rahman'), ('Sk. Shafiq Islaam'),
             ('Dr. Engr. Ch. Raheem'), ('Rahman, Abdur'), ('Mst. Zannat Ara'),
             ('Philip D''Costa'), ('Md.Farook Hossain')) AS t(raw);

-- N2. Raw vs normalized score for the same pairs.
SELECT a, b,
       round(fn_trigram_score(a, b)::numeric, 3)      AS trigram,
       round(fn_trigram_score_norm(a, b)::numeric, 3) AS trigram_norm,
       round(fn_lev_score(a, b)::numeric, 3)          AS lev,
       round(fn_lev_score_norm(a, b)::numeric, 3)     AS lev_norm
FROM (VALUES ('Md. Rahim Uddin',  'Mohammad Rahim Uddin'),
             ('Shafiq Islam',     'Safiq Islaam'),
             ('Abdur Raheem',     'Abdul Rahim'),
             ('Rahim Khan',       'Karim Khan')) AS t(a, b);

-- N3. Gold-pair averages, raw vs normalized (uses the stored column: fast).
SELECT g.is_duplicate,
       count(*) AS pairs,
       round(avg(fn_trigram_score(a.full_name, b.full_name))::numeric, 3)             AS trigram,
       round(avg(fn_trigram_score(a.normalized_name, b.normalized_name))::numeric, 3) AS trigram_norm,
       round(avg(fn_lev_score(a.full_name, b.full_name))::numeric, 3)                 AS lev,
       round(avg(fn_lev_score(a.normalized_name, b.normalized_name))::numeric, 3)     AS lev_norm
FROM gold_pair g
JOIN name_record a ON a.record_id = g.record_id_a
JOIN name_record b ON b.record_id = g.record_id_b
GROUP BY g.is_duplicate;
