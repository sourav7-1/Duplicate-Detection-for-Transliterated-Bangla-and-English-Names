"""Input -> output cases for the SQL function fn_normalize_bn_name (sql/04_normalize.sql).

Needs the database from .env with sql/04_normalize.sql applied and all default rules
active; skipped if the database is unreachable.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from load_data import connect  # noqa: E402

CASES = [
    # prefixes -> one canonical form
    ("Md. Abdur Rahman",        "muhammad abdul rahman"),
    ("MOHAMMED Abdul Rahman",   "muhammad abdul rahman"),
    ("Mohd Rahim",              "muhammad rahim"),
    ("Sk. Shafiq",              "seikh safiq"),          # sheikh, then sh -> s
    ("Ch. Kamal",               "chowdhury kamal"),
    ("Kamal Choudhury",         "kamal chowdhury"),
    # titles removed
    ("Dr. Engr. Rahim",         "rahim"),
    # double vowels
    ("Islaam",                  "islam"),
    ("Raheem",                  "rahim"),
    ("Farook",                  "faruk"),
    # consonant variants
    ("Philip",                  "filip"),
    ("Zannat Ara",              "jannat ara"),
    # punctuation and spacing
    ("Md.Rahim  Uddin",         "muhammad rahim uddin"),
    ("Abu-Bakar",               "abu bakar"),
    # whole-word rules must not fire inside a word ('md' in 'ahmed')
    ("Ahmed Hossain",           "ahmed hossain"),
]


@pytest.fixture(scope="module")
def cur():
    try:
        conn = connect()
    except Exception as e:
        pytest.skip(f"database not available: {e}")
    with conn, conn.cursor() as c:
        yield c


@pytest.mark.parametrize("raw, expected", CASES)
def test_normalize(cur, raw, expected):
    cur.execute("SELECT fn_normalize_bn_name(%s)", (raw,))
    assert cur.fetchone()[0] == expected
