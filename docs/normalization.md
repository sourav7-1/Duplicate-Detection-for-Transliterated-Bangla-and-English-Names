# Normalization Notes (1NF, 2NF, 3NF/BCNF)

These are bullet-point notes for writing the normalization section of the report, based on `sql/01_schema.sql`.

## Keys and functional dependencies

| Table | Candidate keys | Main functional dependencies (FDs) |
|---|---|---|
| person | `person_id` | person_id → canonical_name, is_hard_negative |
| name_record | `record_id` | record_id → person_id, full_name, normalized_name, variant_type, source, created_at |
| name_token | `token_id`; `(record_id, position)` | token_id → all; (record_id, position) → all |
| match_method | `method_id`; `method_name` | method_id → all; method_name → all |
| experiment_run | `run_id` | run_id → method_id, threshold, use_normalization, use_gin_index, dataset_size, started_at, duration_ms, metrics |
| match_result | `result_id`; `(run_id, record_id_a, record_id_b)` | result_id → all; (run_id, a, b) → score, predicted_duplicate |

## 1NF (atomic values, no repeating groups)

- Every column holds one atomic value. There are no arrays, lists or comma-separated values.
- A name with several words is **not** stored as a list inside one column. Each word is its own row in `name_token`, ordered by `position`.
  - That is the classic 1NF fix for a repeating group: token_1, token_2, token_3 become rows.
- One person with many spellings is **not** stored as `variant_1, variant_2, ...` columns on `person`. Each spelling is a row in `name_record`.
- Every table has a primary key, so no two rows are identical.
- A question an examiner may ask: "Isn't `full_name` non-atomic?"
  - Answer: the project treats it as one value, the name as written, and that is what matching compares.
  - The decomposed form lives in `name_token`.
  - `full_name` is kept because the methods being tested (trigram, Levenshtein) work on the whole string.

## 2NF (1NF + no partial dependency on part of a composite key)

- 2NF can only fail when a table has a **composite** candidate key and a non-key column depends on just part of it.
- `person`, `name_record` and `experiment_run` have single-column keys only, so they are in 2NF automatically.
- `name_token` has the composite key `(record_id, position)`.
  - `token`, `normalized_token` and the phonetic codes describe the word at that position, so they need **both** parts.
  - Nothing depends on `record_id` alone. The person a token belongs to is not stored here, which would be a partial dependency; it is reached through `name_record`.
- `match_result` has the composite key `(run_id, record_id_a, record_id_b)`.
  - `score` and `predicted_duplicate` depend on the whole combination: this run scoring this pair.
  - The method and threshold depend on `run_id` alone, so they are **not** repeated here. They live in `experiment_run`.
  - Likewise, the names (dependent on `record_id_a` alone) are not copied here.
- `match_method` has the candidate key `method_name`, but it is a single column, so there is no partial dependency.

## 3NF / BCNF (no transitive dependency; every determinant is a candidate key)

- BCNF rule: for every non-trivial FD X → Y, X must be a superkey. 3NF is slightly weaker, but here meeting BCNF also gives 3NF.
- Each fact is stored in exactly one place:
  - A person's identity is in `person`.
  - A spelling is in `name_record`.
  - A method's definition is in `match_method`.
  - A run's configuration is in `experiment_run`.
  - A pair's score is in `match_result`.
- Transitive dependencies that were deliberately avoided:
  - `match_result` stores `run_id`, **not** `method_id`. Storing both would create run_id → method_id inside `match_result`, a transitive dependency on a non-key.
  - `name_token` stores `record_id`, **not** `person_id`. Storing both would create record_id → person_id.
  - `name_record` stores `person_id`, **not** `canonical_name`. Copying it would create person_id → canonical_name.
- The gold label ("is this pair a real duplicate?") is **not stored**. It follows from `a.person_id = b.person_id`. Storing it would duplicate information already in `name_record`, and the two could drift apart.
- Tables with two candidate keys are still BCNF, because both determinants are keys:
  - `match_method`: `method_id` and `method_name`.
  - `name_token`: `token_id` and `(record_id, position)`.
  - `match_result`: `result_id` and `(run_id, record_id_a, record_id_b)`.

## Honest caveat: derived columns are a deliberate denormalization

Some columns are **computed from other columns**. Strictly, each one adds an FD whose left-hand side is not a key, so a strict examiner would say these columns break 3NF/BCNF. Say this openly in the report rather than claiming a perfect BCNF.

| Column | Derived from | FD (determinant is not a key) |
|---|---|---|
| `name_record.normalized_name` | `full_name` + normalization rules | full_name → normalized_name |
| `name_token.normalized_token`, `soundex_code`, `metaphone_code` | `token` | token → soundex_code, … |
| `match_result.predicted_duplicate` | `score` + the run's `threshold` | (run_id, score) → predicted_duplicate |
| `experiment_run.precision/recall/f1_score` | rows in `match_result` + `person_id` | aggregates of other tables |

- **Why they are kept anyway:**
  - Performance. A GIN trigram index on `normalized_name`, and B-tree indexes on `soundex_code` and `metaphone_code`, are what RQ3 measures.
  - Experiment stability. The normalization rules change between RQ2 ablation runs, so a stored value records which output was actually used.
  - Reporting. The metrics are computed once per run instead of re-aggregating millions of `match_result` rows each time.
- **Why they cause no update anomaly in practice:**
  - They are written only by the pipeline scripts, never edited by hand.
  - They are recomputed whenever their source changes.
- **How to make the schema strictly BCNF, if required:**
  - Drop the columns.
  - Replace each with an expression index, e.g. `CREATE INDEX ON name_token (soundex(token))`, or with a view.
  - Make `predicted_duplicate` a view expression such as `score >= threshold`.
  - Report-friendly wording: "The base schema is in BCNF; the derived columns are a controlled denormalization for performance."
