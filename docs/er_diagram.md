# ER Diagram

```mermaid
erDiagram
    person ||--|{ name_record : "is recorded as"
    name_record ||--|{ name_token : "is split into"
    match_method ||--o{ experiment_run : "is evaluated in"
    experiment_run ||--o{ match_result : "produces"
    name_record ||--o{ match_result : "is record_a of"
    name_record ||--o{ match_result : "is record_b of"

    person {
        int person_id PK
        varchar canonical_name "original spelling"
        boolean is_hard_negative "near-miss of another person"
    }

    name_record {
        int record_id PK
        int person_id FK
        varchar full_name "raw spelling as stored"
        varchar normalized_name "output of Bangla normalization"
        varchar variant_type "original, prefix, typo, hard_negative, ..."
    }

    name_token {
        int token_id PK
        int record_id FK
        smallint position "0-based order in name"
        varchar token
        varchar normalized_token
        varchar soundex_code
        varchar metaphone_code "dmetaphone()"
    }

    match_method {
        int method_id PK
        varchar method_name UK "exact, levenshtein, soundex, dmetaphone, trigram, hybrid"
        varchar sql_function "e.g. similarity(), levenshtein()"
        text description
    }

    experiment_run {
        int run_id PK
        int method_id FK
        numeric threshold "score cutoff for a match"
        boolean use_normalization "RQ2"
        boolean use_gin_index "RQ3"
        int dataset_size "records in name_record"
        timestamp started_at
        numeric duration_ms
        numeric precision_score
        numeric recall_score
        numeric f1_score
    }

    match_result {
        bigint result_id PK
        int run_id FK
        int record_id_a FK "record_id_a < record_id_b"
        int record_id_b FK
        numeric score
        boolean predicted_duplicate
    }
```

## Cardinality

| Relationship | Cardinality | Meaning |
|---|---|---|
| person → name_record | 1 to 1..N | every person has at least the original record |
| name_record → name_token | 1 to 1..N | every name has at least one token |
| match_method → experiment_run | 1 to 0..N | a method may not have been run yet |
| experiment_run → match_result | 1 to 0..N | one row per candidate pair the run scored |
| name_record → match_result | 1 to 0..N (twice) | a record can appear as `record_id_a` or `record_id_b` |

## Notes

- `match_result` has `UNIQUE (run_id, record_id_a, record_id_b)` and `CHECK (record_id_a < record_id_b)`.
- The true label isn't stored. A pair is a real duplicate when both records have the same `person_id`, so it is computed with a join. This keeps precision, recall and F1 in plain SQL.
- `data/gold_pairs.csv` loads into a separate `gold_pair` table used only for evaluation. It isn't part of the core model.
