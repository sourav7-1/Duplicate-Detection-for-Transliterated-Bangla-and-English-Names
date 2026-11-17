# Duplicate Detection for Transliterated Bangla and English Names

DBMS project that detects duplicate person records whose names are written in
Bangla, English, or transliterated forms, using PostgreSQL.

## Structure

| Folder     | Purpose                              |
|------------|--------------------------------------|
| `data/`    | Raw and sample datasets              |
| `sql/`     | Schema, indexes, and queries         |
| `src/`     | Python source code                   |
| `docs/`    | Reports and documentation            |
| `tests/`   | pytest tests                         |
| `results/` | Generated outputs and charts         |

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows (source .venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
cp .env.example .env            # then fill in your PostgreSQL credentials
streamlit run app.py
```

## Tests

```bash
pytest
```
