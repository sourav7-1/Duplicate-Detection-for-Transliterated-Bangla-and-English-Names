# Duplicate Detection for Transliterated Bangla and English Names

A DBMS project that finds duplicate person records whose names are spelled differently
because of transliteration: `Md. Abdur Rahman`, `Mohammad Abdul Rahman` and
`Muhammad Abdur Rohman` are the same person. Everything runs inside **PostgreSQL** using
`pg_trgm` (trigram similarity + GIN index) and `fuzzystrmatch` (Levenshtein, Soundex,
Double Metaphone), plus a rule-based Bangla name normalizer.

**Research questions**

- **RQ1:** Which method (exact, trigram, Levenshtein, Double Metaphone, Soundex) gets the highest F1?
- **RQ2:** How much does custom Bangla name normalization improve each method?
- **RQ3:** How much does a GIN trigram index cut query time, and how does it scale?

## Project structure

| Path | Contents |
|---|---|
| `data/` | `names.csv` (synthetic name records), `gold_pairs.csv` (labelled pairs) |
| `sql/` | `01_schema.sql` … `05_index.sql`, run in order (see below) |
| `src/` | dataset generation, loading, evaluation, benchmark, plots |
| `app.py` | Streamlit demo: search for duplicates, view evaluation results |
| `docs/` | ER diagram, normalization (1NF–BCNF) notes, `figures/`, `explain/` query plans |
| `results/` | `metrics.csv`, `benchmark.csv`, `failure_table.csv` |
| `tests/` | pytest tests |

## Requirements

- Python 3.11+
- PostgreSQL 14+ (tested on 18), with `psql` on your PATH
  (Windows: add `C:\Program Files\PostgreSQL\18\bin` to PATH)

## 1. Installation

Clone the repository, then run everything from the repository root.

Create and activate a virtual environment.

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

macOS / Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install the Python packages:

```bash
python -m pip install -r requirements.txt
```

Create your `.env` from the template, then open `.env` and set `DB_PASSWORD` (and the
other values if yours differ):

```bash
cp .env.example .env
```

(Windows PowerShell: `Copy-Item .env.example .env`)

`.env` is git-ignored; never commit it.

## 2. Create the database and extensions

```bash
psql -U postgres -c "CREATE DATABASE namededup;"
psql -U postgres -d namededup -c "CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;"
```

`psql` asks for the `postgres` password each time. If it cannot connect, add `-h localhost`.

## 3. Generate the dataset

```bash
python src/generate_dataset.py
python src/make_pairs.py
```

- `generate_dataset.py` writes `data/names.csv`: 400 base people, each with an original
  record and 3–8 spelling variants (prefix, vowel, doubled letter, sh/s, ph/f, z/j, oo/u,
  ee/i, initials, word order, typo, spacing, case), plus 20% hard negatives (different
  people with similar names, e.g. Rahim vs Karim). It uses seed 42, so the output is
  identical every run. For a larger dataset run, for example,
  `python src/generate_dataset.py --size 5000`.
- `make_pairs.py` writes `data/gold_pairs.csv`: all duplicate pairs plus an equal number of
  non-duplicate pairs: every hard negative paired with each record of the person it imitates,
  then similar names of different people drawn evenly from three pools (trigram >= 0.5, same
  Double Metaphone codes, Levenshtein >= 0.7), then random pairs to fill. The `source` column
  says which rule picked each pair. Needs sql/02 and sql/03 applied (it scores in PostgreSQL).

## 4. Build the schema, load data, create functions and indexes

Run these **in this order**:

```bash
psql -U postgres -d namededup -f sql/01_schema.sql
python src/load_data.py
psql -U postgres -d namededup -f sql/02_methods_basic.sql
psql -U postgres -d namededup -f sql/03_methods_phonetic.sql
psql -U postgres -d namededup -f sql/04_normalize.sql
psql -U postgres -d namededup -f sql/05_index.sql
```

| Step | What it does |
|---|---|
| `01_schema.sql` | Tables, keys and constraints. **Drops and recreates the tables**, so all data is lost. |
| `load_data.py` | Loads `names.csv` and `gold_pairs.csv` with `COPY` (replaces existing rows) |
| `02_methods_basic.sql` | `fn_trigram_score`, `fn_lev_score` |
| `03_methods_phonetic.sql` | `fn_phonetic_score` (Double Metaphone), `fn_soundex_score` |
| `04_normalize.sql` | `name_variant_rule` table, `fn_normalize_bn_name`, fills `normalized_name` |
| `05_index.sql` | GIN trigram indexes + example `EXPLAIN ANALYZE` plans |

Each SQL file ends with example queries, so it prints result tables as it runs.

**Note:** `load_data.py` leaves `normalized_name` empty. Whenever you reload the data,
run `sql/04_normalize.sql` again afterwards.

## 5. Run the experiments

```bash
python src/evaluate.py
python src/benchmark.py
python src/plots.py
```

| Script | Output |
|---|---|
| `evaluate.py` (RQ1, RQ2) | Scores every gold pair with every method, raw and normalized, and sweeps the threshold from 0.30 to 0.95 in steps of 0.05. Also tries three Hybrid weight sets (Double Metaphone / trigram / Levenshtein on normalized names: 0.4/0.4/0.2, 0.5/0.3/0.2, 0.34/0.33/0.33). Writes `results/metrics.csv`, `results/metrics_by_source.csv` (per `gold_pair.source` at each best threshold), `results/hybrid_weights.json` (the best Hybrid set, which the app's Hybrid method uses) and the `experiment_run` / `match_result` tables. |
| `benchmark.py` (RQ3) | Query time at 1k / 10k / 100k records with and without the GIN index, 5 runs each. Writes `results/benchmark.csv` and plans in `docs/explain/`. Uses a scratch table, so your data is untouched. |
| `plots.py` | Figures in `docs/figures/` and `results/failure_table.csv` |

## 6. Run the app

```bash
streamlit run app.py
```

Then open http://localhost:8501. If the `streamlit` command is not found or is blocked,
use `python -m streamlit run app.py` instead.

The **Search** tab takes a name and a method (Trigram, Levenshtein, Phonetic, Custom
normalization, Hybrid) plus a threshold. It shows the top 10 possible duplicates with
their scores, normalized names and query time. The **Evaluation results** tab shows the
F1 table and chart.

## 7. Run the tests

```bash
pytest
```

`tests/test_normalize.py` needs the database (steps 2–4) and is skipped if it cannot connect.

## Results

Best threshold per method on the default dataset (2,691 records, 15,586 gold pairs: 7,793
duplicates; 7,793 non-duplicates of which 541 hard-negative, 2,656 trigram, 31 dmetaphone,
2,276 levenshtein and 2,289 random), threshold sweep 0.30–0.95, from `results/metrics.csv`:

| Method | Normalized | Best threshold | Precision | Recall | F1 |
|---|---|---:|---:|---:|---:|
| hybrid 0.50/0.30/0.20 (DM/tri/lev) | yes | 0.70 | 0.927 | 0.756 | 0.833 |
| hybrid 0.40/0.40/0.20 | yes | 0.65 | 0.873 | 0.792 | 0.830 |
| dmetaphone | yes | 0.75 | 0.944 | 0.729 | 0.823 |
| soundex | yes | 0.75 | 0.937 | 0.729 | 0.820 |
| hybrid 0.34/0.33/0.33 | yes | 0.70 | 0.911 | 0.734 | 0.813 |
| trigram | yes | 0.60 | 0.834 | 0.784 | 0.808 |
| soundex | no | 0.75 | 0.940 | 0.703 | 0.804 |
| dmetaphone | no | 0.65 | 0.798 | 0.756 | 0.777 |
| trigram | no | 0.55 | 0.785 | 0.750 | 0.767 |
| levenshtein | yes | 0.85 | 0.911 | 0.627 | 0.743 |
| levenshtein | no | 0.80 | 0.882 | 0.626 | 0.732 |
| exact | yes | 0.95 | 1.000 | 0.329 | 0.495 |
| exact | no | 0.95 | 1.000 | 0.069 | 0.129 |

The app's Hybrid uses the winning set, 0.50/0.30/0.20 (`results/hybrid_weights.json`).

False-positive rate per non-duplicate source, normalized names, each method at its best
threshold (`results/metrics_by_source.csv`):

| Method | hard negative | trigram | dmetaphone (n=31) | levenshtein | random |
|---|---:|---:|---:|---:|---:|
| exact | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| trigram | 53.6% | 21.8% | 71.0% | 14.5% | 0.0% |
| levenshtein | 46.8% | 2.7% | 19.4% | 6.4% | 0.0% |
| dmetaphone | 26.6% | 4.2% | 74.2% | 2.5% | 0.0% |
| soundex | 25.5% | 4.9% | 74.2% | 4.0% | 0.0% |
| hybrid 0.50/0.30/0.20 | 39.4% | 4.6% | 87.1% | 4.5% | 0.0% |

Query time at 100k records, mean of 10 search names × 5 runs (`results/benchmark.csv`):

| Method | No index (ms) | GIN (ms) | Speedup |
|---|---:|---:|---:|
| exact | 352.0 | 44.7 | 7.9× |
| trigram | 347.9 | 48.9 | 7.1× |
| levenshtein | 385.7 | 88.0 | 4.4× |
| dmetaphone | 487.6 | 168.0 | 2.9× |
| soundex | 471.7 | 162.3 | 2.9× |

Figures: `docs/figures/f1_by_method.png`, `pr_curves.png`, `fp_by_source.png`,
`query_time_scaling.png`, `failure_table.png`.

**Caveats**

- Every best threshold lies inside the 0.30–0.95 sweep. None sit at its lower edge, so widening the sweep further would not change them.
- The dmetaphone source has only 31 pairs, so its false-positive rates move by 3.2 points per pair.
- With the GIN index, query time varies a lot between search names (dmetaphone: mean 168 ms, std 186 ms, min 35 ms). The scaling chart's lower whiskers stop at the fastest run, because mean − std falls below zero. Names that share common words such as "Md." or "Islam" have many trigram candidates to rescore.
- Hybrid weights and thresholds were chosen on the same gold pairs they are reported on, with no held-out split, so Hybrid's F1 is slightly optimistic.
