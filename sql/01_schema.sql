-- 01_schema.sql
-- Schema for "Duplicate Detection for Transliterated Bangla and English Names".
-- Run: psql -U postgres -d namededup -f sql/01_schema.sql
--
-- WARNING: re-running drops these tables and all their data.

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;

DROP TABLE IF EXISTS gold_pair, match_result, experiment_run, match_method,
                     name_token, name_record, person CASCADE;

-- A real-world individual. IDs come from data/names.csv, so no IDENTITY.
CREATE TABLE person (
    person_id         INTEGER      PRIMARY KEY,
    canonical_name    VARCHAR(150) NOT NULL CHECK (btrim(canonical_name) <> ''),
    is_hard_negative  BOOLEAN      NOT NULL DEFAULT FALSE
);

-- One stored spelling of a person's name.
CREATE TABLE name_record (
    record_id        INTEGER      PRIMARY KEY,
    person_id        INTEGER      NOT NULL
                                  REFERENCES person (person_id) ON DELETE CASCADE,
    full_name        VARCHAR(150) NOT NULL CHECK (btrim(full_name) <> ''),
    normalized_name  VARCHAR(150),            -- NULL until normalization runs
    variant_type     VARCHAR(20)  NOT NULL CHECK (variant_type IN (
                         'original', 'prefix', 'vowel', 'double_letter', 'sh_s',
                         'ph_f', 'z_j', 'oo_u', 'ee_i', 'initials', 'word_order',
                         'typo', 'spacing', 'case', 'hard_negative')),
    source           VARCHAR(30)  NOT NULL DEFAULT 'synthetic'
                                  CHECK (source IN ('synthetic', 'manual', 'import')),
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- One word of a name (e.g. "Md." / "Rahim" / "Uddin"), for per-token phonetic matching.
CREATE TABLE name_token (
    token_id          INTEGER     GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    record_id         INTEGER     NOT NULL
                                  REFERENCES name_record (record_id) ON DELETE CASCADE,
    position          SMALLINT    NOT NULL CHECK (position >= 0),
    token             VARCHAR(60) NOT NULL CHECK (token <> ''),
    normalized_token  VARCHAR(60),
    soundex_code      CHAR(4),
    metaphone_code    VARCHAR(10),
    UNIQUE (record_id, position)
);

-- A matching technique being compared (exact, levenshtein, soundex, ...).
CREATE TABLE match_method (
    method_id     INTEGER     GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    method_name   VARCHAR(30) NOT NULL UNIQUE CHECK (method_name = lower(method_name)),
    sql_function  VARCHAR(60) NOT NULL,
    description   TEXT
);

-- One execution of one method under one configuration (threshold, normalization, index).
CREATE TABLE experiment_run (
    run_id             INTEGER      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    method_id          INTEGER      NOT NULL
                                    REFERENCES match_method (method_id) ON DELETE RESTRICT,
    threshold          NUMERIC(6,3) NOT NULL CHECK (threshold >= 0),
    use_normalization  BOOLEAN      NOT NULL,
    use_gin_index      BOOLEAN      NOT NULL,
    dataset_size       INTEGER      NOT NULL CHECK (dataset_size > 0),
    started_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    duration_ms        NUMERIC(12,3) CHECK (duration_ms >= 0),
    precision_score    NUMERIC(5,4) CHECK (precision_score BETWEEN 0 AND 1),
    recall_score       NUMERIC(5,4) CHECK (recall_score    BETWEEN 0 AND 1),
    f1_score           NUMERIC(5,4) CHECK (f1_score        BETWEEN 0 AND 1)
);

-- The score a run gave one candidate pair of records.
CREATE TABLE match_result (
    result_id            BIGINT   GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id               INTEGER  NOT NULL
                                  REFERENCES experiment_run (run_id) ON DELETE CASCADE,
    record_id_a          INTEGER  NOT NULL
                                  REFERENCES name_record (record_id) ON DELETE CASCADE,
    record_id_b          INTEGER  NOT NULL
                                  REFERENCES name_record (record_id) ON DELETE CASCADE,
    score                NUMERIC(8,4) NOT NULL,
    predicted_duplicate  BOOLEAN  NOT NULL,
    CHECK (record_id_a < record_id_b),          -- each unordered pair stored once
    UNIQUE (run_id, record_id_a, record_id_b)
);

-- Evaluation only: labelled pairs from data/gold_pairs.csv (not part of the core ER model).
CREATE TABLE gold_pair (
    record_id_a   INTEGER  NOT NULL REFERENCES name_record (record_id) ON DELETE CASCADE,
    record_id_b   INTEGER  NOT NULL REFERENCES name_record (record_id) ON DELETE CASCADE,
    is_duplicate  BOOLEAN  NOT NULL,
    -- how make_pairs.py chose the pair, for per-source results
    source        VARCHAR(15) NOT NULL CHECK (source IN ('duplicate', 'hard_negative',
                      'trigram', 'dmetaphone', 'levenshtein', 'random')),
    CHECK (is_duplicate = (source = 'duplicate')),
    PRIMARY KEY (record_id_a, record_id_b),
    CHECK (record_id_a < record_id_b)
);
