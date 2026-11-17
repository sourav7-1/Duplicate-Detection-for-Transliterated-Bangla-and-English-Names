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
  random non-duplicate pairs.

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
| `evaluate.py` (RQ1, RQ2) | Scores every gold pair with every method, raw and normalized, and sweeps the threshold from 0.50 to 0.95. Writes `results/metrics.csv` and the `experiment_run` / `match_result` tables. |
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

Best threshold per method on the default dataset (2,691 records, 15,586 gold pairs), from
`results/metrics.csv`:

| Method | Normalized | Best threshold | Precision | Recall | F1 |
|---|---|---:|---:|---:|---:|
| dmetaphone | yes | 0.50 | 0.988 | 0.914 | 0.950 |
| soundex | yes | 0.50 | 0.988 | 0.914 | 0.949 |
| soundex | no | 0.50 | 0.990 | 0.911 | 0.949 |
| dmetaphone | no | 0.50 | 0.990 | 0.904 | 0.945 |
| trigram | yes | 0.50 | 0.997 | 0.873 | 0.931 |
| trigram | no | 0.50 | 0.999 | 0.835 | 0.909 |
| levenshtein | no | 0.50 | 0.983 | 0.805 | 0.886 |
| levenshtein | yes | 0.50 | 0.968 | 0.804 | 0.878 |
| exact | yes | 0.95 | 1.000 | 0.288 | 0.447 |
| exact | no | 0.95 | 1.000 | 0.069 | 0.129 |

Figures: `docs/figures/f1_by_method.png`, `pr_curves.png`, `query_time_scaling.png`,
`failure_table.png`.

**Caveats**

- 0.50 is the lowest threshold in the sweep, so the true best thresholds may be lower.
- The non-duplicate pairs are random and rarely near-misses, so precision is optimistic.
