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
    ("Md. Abdur Rahman",        "muhamad abdul rahman"),   # muhammad -> muhamad (doubled m)
    ("MOHAMMED Abdul Rahman",   "muhamad abdul rahman"),
    ("Mohd Rahim",              "muhamad rahim"),
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
    ("Zannat Ara",              "janat ara"),
    # punctuation and spacing
    ("Md.Rahim  Uddin",         "muhamad rahim udin"),
    ("Abu-Bakar",               "abu bakar"),
    # whole-word rules must not fire inside a word ('md' in 'ahmed')
    ("Ahmed Hossain",           "ahmed hosain"),
    # doubled consonants collapse to one
    ("Rassel",                  "rasel"),
    ("Md. Rakib Rahmman",       "muhamad rakib rahman"),
    ("Asshok Dey",              "asok dey"),             # ssh -> sh -> s
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


def test_collapse_runs_before_common_token_strip(cur):
    # The typo "Rahmman" only becomes the common token "rahman" after normalization,
    # so stripping must see the normalized name: then both spellings agree on "rakib".
    cur.execute("SELECT fn_strip_common_tokens(fn_normalize_bn_name(%s)), "
                "fn_strip_common_tokens(fn_normalize_bn_name(%s))",
                ("Md. Rakib Rahmman", "Mohammad Rakib Rahman"))
    assert cur.fetchone() == ("rakib", "rakib")
