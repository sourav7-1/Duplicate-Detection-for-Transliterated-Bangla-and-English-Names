"""Data access for the app: every SQL call, plus reading results/metrics.csv."""
import time
from textwrap import dedent

from psycopg import ClientCursor

from plots import RESULTS, read_csv
from ui.db import get_conn

# Hybrid = weighted mix of three normalized scores (not yet evaluated in metrics.csv).
HYBRID_WEIGHTS = {"trigram": 0.4, "levenshtein": 0.3, "phonetic": 0.3}

# method -> (score SQL, optional index-backed prefilter). %(q)s = raw query,
# %(nq)s = normalized query. Trigram methods use the GIN index through the % operator.
METHODS = {
    "Custom normalization": ("similarity(normalized_name, %(nq)s)", "normalized_name %% %(nq)s"),
    "Trigram": ("similarity(full_name, %(q)s)", "full_name %% %(q)s"),
    "Levenshtein": ("fn_lev_score(full_name, %(q)s)", None),
    "Double Metaphone": ("fn_phonetic_score(full_name, %(q)s)", None),
    "Soundex": ("fn_soundex_score(full_name, %(q)s)", None),
    "Hybrid": (
        f"{HYBRID_WEIGHTS['trigram']} * fn_trigram_score(normalized_name, %(nq)s)"
        f" + {HYBRID_WEIGHTS['levenshtein']} * fn_lev_score(normalized_name, %(nq)s)"
        f" + {HYBRID_WEIGHTS['phonetic']} * fn_phonetic_score(normalized_name, %(nq)s)",
        None,
    ),
}
METHOD_NAMES = list(METHODS)


def search(name, method, threshold):
    """Top 10 records scoring >= threshold.

    Returns (normalized query, rows, elapsed ms, sql) where
    rows = [(record_id, person_id, full_name, normalized_name, score), ...] and
    sql  = the exact statements sent to PostgreSQL. A ClientCursor binds the values
           into the SQL text itself, so what is shown is byte-for-byte what ran.
    """
    score_sql, prefilter = METHODS[method]
    where = f"WHERE {prefilter}" if prefilter else ""
    query = dedent(f"""\
        SELECT record_id, person_id, full_name, normalized_name, score
        FROM (SELECT record_id, person_id, full_name, normalized_name,
                     ({score_sql})::float8 AS score
              FROM name_record {where}) AS s
        WHERE score >= %(t)s
        ORDER BY score DESC, record_id
        LIMIT 10""")
    with ClientCursor(get_conn()) as cur:
        t0 = time.perf_counter()
        normalize_sql = cur.mogrify(
            "SELECT fn_normalize_bn_name(%s), "
            "set_config('pg_trgm.similarity_threshold', %s, false)",
            (name, str(threshold)))
        cur.execute(normalize_sql)
        nq = cur.fetchone()[0]
        search_sql = cur.mogrify(query, {"q": name, "nq": nq, "t": threshold})
        cur.execute(search_sql)
        rows = cur.fetchall()
        elapsed_ms = (time.perf_counter() - t0) * 1000
    return nq, rows, elapsed_ms, f"{normalize_sql};\n\n{search_sql};"


def dataset_sizes():
    """Record counts of the datasets loaded in the database (empty list if none).

    Only name_record holds searchable data today; the benchmark sizes live in a
    scratch table that benchmark.py drops, so they are not listed.
    """
    with get_conn().cursor() as cur:
        cur.execute("SELECT count(*) FROM name_record")
        n = cur.fetchone()[0]
    return [n] if n else []


def load_metrics():
    """Rows of results/metrics.csv as dicts, or None if evaluate.py hasn't been run."""
    path = RESULTS / "metrics.csv"
    return read_csv(path) if path.exists() else None


def load_benchmark():
    """Rows of results/benchmark.csv as dicts, or None if benchmark.py hasn't been run."""
    path = RESULTS / "benchmark.csv"
    return read_csv(path) if path.exists() else None
